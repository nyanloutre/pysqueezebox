"""
The following tests check the integration between pysqueezebox and a real
Logitech Media Server.

PLEASE TAKE NOTE: All of these tests are designed to run on a Squeezebox system
without unduly interfering with normal service. This means that they must not raise
the volume and must leave the player in the same state as they found it in.

PLEASE RESPECT THIS.
"""
import asyncio
import aiohttp
import pytest
from pysqueezebox import Player, Server, async_discover
from conftest import compare_playlists

# pylint: disable=C0103
# All test coroutines will be treated as marked.
pytestmark = pytest.mark.asyncio

IP = None


@pytest.fixture(name="lms", scope="module")
async def fixture_lms(request):
    """Return a working Server object."""
    # Get the ip address and port from the command line
    ip = IP if IP else request.config.option.IP
    port = request.config.option.PORT

    if ip is None:
        pytest.fail("No ip address specified. Use the --ip option.")

    async with aiohttp.ClientSession() as session:
        server = Server(session, ip, port)
        # confirm server is working
        assert await server.async_status()
        yield server


@pytest.fixture(name="player", scope="module")
async def fixture_player(lms):
    """Return a working Player object."""
    players = await lms.async_get_players()
    if len(players) < 1:
        pytest.fail("No players found. You can use a virtual player like squeezelite.")
    test_player = players[0]
    assert isinstance(test_player, Player)
    assert await test_player.async_update()

    power = test_player.power
    mode = test_player.mode
    playlist = test_player.playlist.copy()

    yield test_player

    await test_player.async_pause()
    await test_player.async_clear_playlist()
    if playlist:
        await test_player.async_load_playlist(playlist, "add")
    await test_player.async_set_power(power)
    if mode == "play":
        await test_player.async_play()


@pytest.fixture(name="broken_player", scope="module")
async def broken_player_fixture(lms):
    """Return a Player that does not work."""
    broken_player = Player(lms, "NOT A PLAYER ID", "Bogus player")
    assert not await broken_player.async_update()
    yield broken_player


@pytest.fixture(name="test_uris", scope="module")
async def fixture_test_uris(player):
    """Return the first three songs in the database to use in playlist tests."""
    test_songs = (await player.async_query("songs", "0", "3", "tags:u"))["titles_loop"]
    assert len(test_songs) == 3
    test_uris = [i["url"] for i in test_songs]
    return test_uris


@pytest.fixture(name="test_album", scope="module")
async def fixture_test_album(player):
    """Return the first album in the database with multiple coverart tracks to use in
    album art test."""
    test_albums = (await player.async_query("albums", "0", "10"))["albums_loop"]
    for album in test_albums:
        tracks = (
            await player.async_query(
                "tracks", "0", "2", f"album_id:{album['id']}", "tags:ju"
            )
        )
        if tracks["count"] > 1 and "coverart" in tracks["titles_loop"][0]:
            return [track["url"] for track in tracks["titles_loop"]]

    pytest.fail("Couldn't find album with cover art and 2+ tracks")


async def test_discovery_integration():
    """Test discovery - requires actual discoverable server."""
    event = asyncio.Event()

    def _discovery_callback(server):
        global IP
        IP = server.host
        event.set()

    task = asyncio.create_task(async_discover(_discovery_callback))
    try:
        await asyncio.wait_for(event.wait(), 1)
    except asyncio.TimeoutError:
        pytest.fail("Synchronous discovery failed")
    task.cancel()
    await task


async def test_server_status(lms):
    """Test server.async_status() method."""
    print(await lms.async_status())
    assert lms.uuid is not None  # should be set by async_status()


async def test_get_players(lms):
    """Test server.async_get_players() method."""
    players = await lms.async_get_players()
    for player in players:
        assert isinstance(player, Player)
    await lms.async_status()
    assert len(players) == lms.status["player count"]


async def test_get_player(lms, player):
    """
    Tests server.async_get_player() method.

    Server referenced by 'lms'  must have at least one player active.
    """
    test_player_a = await lms.async_get_player(name=player.name)
    test_player_b = await lms.async_get_player(player_id=player.player_id)
    assert test_player_a.name == test_player_b.name
    assert test_player_a.player_id == test_player_b.player_id

    # test that we properly return None when there is no matching player
    test_player_none = await lms.async_get_player(name="NO SUCH PLAYER")
    assert test_player_none is None
    test_player_none = await lms.async_get_player(player_id="NO SUCH ID")
    assert test_player_none is None

    # check that we handle a name as player_id correctly
    test_player_c = await lms.async_get_player(player.name)
    assert player.player_id == test_player_c.player_id


async def test_player_properties(player, broken_player):
    """Tests each player property."""
    for p in dir(Player):
        prop = getattr(Player, p)
        if isinstance(prop, property):
            print(f"{p}: {prop.fget(player)}")
    for p in dir(Player):
        prop = getattr(Player, p)
        if isinstance(prop, property):
            print(f"{p}: {prop.fget(broken_player)}")
    assert broken_player.power is None


async def test_async_query(player):
    """Tests Player.async_query()."""
    # test query with result
    result = await player.async_query("status")
    assert result["mode"] in ["play", "pause", "stop"]
    # test query with no result
    result = await player.async_query("pause", "1")
    assert result
    # test bad query
    result = await player.async_query("invalid")
    assert not result


async def test_player_power(player, broken_player):
    """Tests Player power controls."""
    assert await player.async_set_power(True)
    assert not await broken_player.async_set_power(True)
    await player.async_update()
    assert player.power
    assert await player.async_set_power(False)
    await player.async_update()
    assert not player.power
    assert await player.async_set_power(True)
    await player.async_update()
    assert player.power


async def test_player_muting(player, broken_player):
    """Test Player muting controls."""
    assert await player.async_update()
    muting = player.muting
    assert await player.async_set_muting(True)
    await player.async_update()
    assert player.muting
    assert await player.async_set_muting(True)
    await player.async_update()
    assert player.muting
    assert await player.async_set_muting(False)
    await player.async_update()
    assert not player.muting
    await player.async_set_muting(muting)
    assert not await broken_player.async_set_muting(True)


async def test_player_volume(player, broken_player):
    """Test Player volume controls."""
    assert await player.async_update()
    muting = player.muting
    assert await player.async_set_muting(True)
    assert await player.async_update()
    vol = player.volume
    assert 0 <= vol <= 100

    new_vol = vol + 5 if vol < 6 else vol - 5
    assert await player.async_set_volume(new_vol)
    await player.async_update()
    assert player.volume == new_vol

    assert await player.async_set_volume(vol)
    assert await player.async_set_muting(muting)

    assert not await broken_player.async_set_volume(new_vol)


async def test_player_play_pause(player, broken_player):
    """Test play and pause controls."""
    assert await player.async_set_muting(True)

    assert await player.async_play()
    assert not await broken_player.async_play()
    await asyncio.sleep(2)
    await player.async_update()
    assert player.mode == "play"

    assert await player.async_play()
    await asyncio.sleep(2)
    await player.async_update()
    assert player.mode == "play"

    assert await player.async_pause()
    assert not await broken_player.async_pause()
    await asyncio.sleep(2)
    await player.async_update()
    assert player.mode == "pause"

    assert await player.async_pause()
    await asyncio.sleep(2)
    await player.async_update()
    assert player.mode == "pause"

    assert await player.async_toggle_pause()
    assert not await broken_player.async_toggle_pause()
    await asyncio.sleep(2)
    await player.async_update()
    assert player.mode == "play"


async def test_player_load_url_and_index(player, broken_player, test_uris):
    """Test loading and unloading playlist."""
    assert await player.async_clear_playlist()
    assert not await broken_player.async_clear_playlist()
    await player.async_update()
    assert player.playlist is None

    assert await player.async_load_url(test_uris[0], "play")
    await player.async_update()
    assert len(player.playlist) == 1
    assert player.current_track["url"] == test_uris[0]
    assert await player.async_load_url(test_uris[1], "play")
    await player.async_update()
    assert len(player.playlist) == 1
    assert player.current_track["url"] == test_uris[1]

    assert await player.async_load_url(test_uris[0], "add")
    assert await player.async_load_url(test_uris[1], "add")
    assert not await broken_player.async_load_url(test_uris[0], "add")
    await player.async_update()
    assert len(player.playlist) == 3

    assert await player.async_index(0)
    await player.async_update()
    current_track = player.current_track
    assert await player.async_index("+1")
    await player.async_update()
    next_track = player.current_track
    assert current_track != next_track
    assert await player.async_index("-1")
    await player.async_update()
    assert current_track == player.current_track
    assert not await broken_player.async_index(0)

    assert await player.async_load_url(test_uris[2], "insert")
    assert not await broken_player.async_load_url(test_uris[2], "insert")
    await player.async_index("+1")
    await player.async_update()
    assert player.current_track["url"] == test_uris[2]


async def test_player_playlist(player, broken_player, test_uris):
    """Test functions for loading a playlist."""
    test_playlist = [{"url": test_uris[0]}, {"url": test_uris[1]}]

    assert await player.async_clear_playlist()
    await player.async_update()
    assert player.playlist is None

    assert await player.async_load_playlist(test_playlist, "add")
    assert not await broken_player.async_load_playlist(test_playlist, "add")
    await player.async_update()
    assert compare_playlists(test_playlist, player.playlist)

    assert await player.async_load_playlist(reversed(test_playlist), "play")
    assert not await broken_player.async_load_playlist(test_playlist, "play")
    await player.async_update()
    assert compare_playlists(list(reversed(test_playlist)), player.playlist)

    await player.async_index(0)
    assert await player.async_load_playlist(test_playlist, "insert")
    assert not await broken_player.async_load_playlist(test_playlist, "insert")
    await player.async_update()
    current_playlist = test_playlist[1:] + test_playlist + test_playlist[:1]
    assert compare_playlists(current_playlist, player.playlist)


async def test_player_coverart(player, broken_player, test_album):
    """Test album cover art."""
    await player.async_clear_playlist()
    await player.async_load_url(test_album, "add")
    await player.async_update()
    assert len(player.playlist) > 1
    image_url = player.image_url
    assert player.image_url
    await player.async_index("+1")
    await asyncio.sleep(1)
    await player.async_update()
    assert player.image_url == image_url  # should be identical for every track

    assert "/music/unknown/cover.jpg" in broken_player.image_url


async def test_player_shuffle(player, broken_player):
    """Test setting shuffle mode."""
    await player.async_update()
    shuffle_mode = player.shuffle

    for mode in ["none", "song", "album"]:
        assert await player.async_set_shuffle(mode)
        assert not await broken_player.async_set_shuffle(mode)
        await player.async_update()
        assert mode == player.shuffle

    await player.async_set_shuffle(shuffle_mode)


async def test_player_repeat(player, broken_player):
    """Test setting player repeat mode."""
    await player.async_update()
    repeat_mode = player.repeat

    for mode in ["none", "song", "playlist"]:
        assert await player.async_set_repeat(mode)
        assert not await broken_player.async_set_repeat(mode)
        await player.async_update()
        assert mode == player.repeat

    await player.async_set_repeat(repeat_mode)


async def test_player_sync(lms, broken_player):
    players = await lms.async_get_players()
    muting = {}
    sync_master = {}

    test_master = players[0]
    for player in players:
        # mute all players
        await player.async_update()
        muting[player.player_id] = player.muting
        await player.async_set_muting(True)
        sync_master[player.player_id] = player.sync_master
        if player.synced:
            assert await player.async_unsync()
            await player.async_update()
            assert not player.synced
        assert await player.async_sync(test_master)
        await player.async_update()
        assert (
            test_master.player_id in player.sync_group
            or test_master.player_id in player.player_id
        )
        assert await player.async_unsync()
        await player.async_update()
        assert not player.synced
        assert await player.async_sync(test_master.player_id)
        await player.async_update()
        assert (
            test_master.player_id in player.sync_group
            or test_master.player_id in player.player_id
        )

    for player in players:
        await player.async_unsync()

    for player in players:
        if player in sync_master:
            player.async_sync(sync_master[player.player_id])
        await player.async_set_muting(muting[player.player_id])