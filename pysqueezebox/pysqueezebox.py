"""
This a library to control a Logitech Media Server asynchronously, intended for
integration with Home Assistant.

Much of the code was adapted from the Home Assistant squeezebox integration.
The current convention is for all API-specific code to be part of a third
party library hosted on PyPi, so I created a separate library.

The function names track the terms used by the LMS API, so they do not all
match the old Home Assistant squeezebox integration.

Thank you to the original author of the squeezebox integration. If it is you,
please let me know so I can credit you here.

(c) 2020 Raj Laud raj.laud@gmail.com
"""
import urllib
import logging
import json
import asyncio
import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 9000
TIMEOUT = 10
REPEAT_MODE = ['none', 'song', 'playlist']
SHUFFLE_MODE = ['none', 'song', 'album']

class Server:
    """
    Represents a Logitech media server.

    Right now, only those features used by the pre-existing Home Assistant
    squeezebox integration are implemented.
    """

    # pylint: disable=too-many-arguments
    def __init__(self, session, host, port=DEFAULT_PORT, username=None,
                 password=None):
        """
        Initialize the Logitech device.

        Parameters:
            session: aiohttp.ClientSession for connecting to server (required)
            host: LMS server to connect with (required)
            port: LMS server port (optional, default 9000)
            username: LMS username (optional)
            password: LMS password (optional)

        """
        self.host = host
        self.port = port
        self._session = session
        self._username = username
        self._password = password

    async def async_get_players(self):
        """Return Player for each device connected to LMS."""
        players = []
        data = await self.async_query("players", "status")
        if data is False:
            return None
        for player in data.get("players_loop", []):
            players.append(Player(self, player["playerid"], player["name"]))
        return players

    async def async_get_player(self, player_id=None, name=None):
        """Return Player for a device, searching by name or player_id"""
        if player_id:
            data = await self.async_query("status", player=player_id)
            if data:
                name = data["player_name"]
                if name:
                    return Player(self, player_id, name)
            _LOGGER.debug("Unable to find player with id: %s", player_id)
            return None
        if name:
            players = await self.get_players()
            for player in players:
                if name.lower() == player.name.lower():
                    return player
            _LOGGER.debug("Unable to find player with name: %s", name)
            return None
        _LOGGER.error("get_player called without name or player_id")
        return None

    async def async_query(self, *command, player=""):
        """Returns result of query on the JSON-RPC connection."""
        auth = (
            None
            if self._username is None
            else aiohttp.BasicAuth(self._username, self._password)
        )
        url = f"http://{self.host}:{self.port}/jsonrpc.js"
        data = json.dumps(
            {"id": "1", "method": "slim.request", "params": [player, command]}
        )

        _LOGGER.debug("URL: %s Data: %s", url, data)

        try:
            with async_timeout.timeout(TIMEOUT):
                response = await self._session.post(url, data=data, auth=auth)

                if response.status != 200:
                    _LOGGER.error(
                        "Query failed, response code: %s Full message: %s",
                        response.status,
                        response,
                    )
                    return False

                data = await response.json()

        except (asyncio.TimeoutError, aiohttp.ClientError) as error:
            _LOGGER.error("Failed communicating with LMS: %s", type(error))
            return False

        try:
            result = data["result"]
            if not result:
                # a successful command will return an empty result
                return True
            return result
        except AttributeError:
            _LOGGER.error("Received invalid response: %s", data)


# pylint: disable=too-many-public-methods
class Player:
    """Representation of a SqueezeBox device."""

    def __init__(self, lms, player_id, name, status=None):
        """
        Initialize the SqueezeBox device.

        Parameters:
            lms: the Server object controlling the player (required)
            player_id: the unique identifier for the player (required)
            name: the player's name (required)
            status: status dictionary for player (optional)
        """
        self._lms = lms
        self._id = player_id
        self._status = status if status else {}
        self._name = name

        _LOGGER.debug("Creating SqueezeBox object: %s, %s", name, player_id)

    def __repr__(self):
        """Return representation of Player object."""
        return f'Player({self._lms}, {self._id}, {self._name}, {self._status}'

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def player_id(self):
        """Return the player ID, which is its MAC address."""
        return self._id

    @property
    def power(self):
        """Return the power state of the device."""
        if "power" in self._status:
            return self._status["power"] == 1
        return None

    @property
    def mode(self):
        """Return the mode of the device. One of play, stop, or pause."""
        if "mode" in self._status:
            return self._status["mode"]
        return None

    @property
    def volume(self):
        """
        Returns volume level of the Player.
        Returns integer from 0 to 100.
        LMS will return a negative integer if the volume is muted. This leads
        to inconsistent results if you later try to update the volume with
        the negative number, which is instead interpreted as a decrement.
        We return the absolute value, separating out volume from muting.
        """
        if "mixer volume" in self._status:
            return abs(int(float(self._status["mixer volume"])))
        return None

    @property
    def muting(self):
        """Return true if volume is muted."""
        if "mixer volume" in self._status:
            return str(self._status["mixer volume"]).startswith("-")
        return None

    @property
    def current_title(self):
        """
        Return title of current playing media (formatted for player). For
        streams, this gives the title of the current track.
        """
        if "current_title" in self._status:
            return self._status["current_title"]
        return None

    @property
    def duration(self):
        """Return duration of current playing media in seconds."""
        if "duration" in self._status:
            return int(float(self._status["duration"]))
        return None

    @property
    def time(self):
        """
        Return position of current playing media in seconds.
        The LMS API calls this "time" so we follow that convention.
        """
        if "time" in self._status:
            return int(float(self._status["time"]))
        return None

    @property
    def image_url(self):
        """Return image url of current playing media."""
        image_url = (f"/music/current/cover.jpg?player={self._id}")

        # pylint: disable=protected-access
        if self._lms._username:
            base_url = "http://{username}:{password}@{server}:{port}/".format(
                username=self._lms._username,
                password=self._lms._password,
                server=self._lms.host,
                port=self._lms.port,
            )
        else:
            base_url = "http://{server}:{port}/".format(
                server=self._lms.host, port=self._lms.port
            )

        url = urllib.parse.urljoin(base_url, image_url)

        return url

    @property
    def current_track(self):
        """Return playlistLoop dictionary for current track"""
        try:
            cur_index = int(self._status["playlist_cur_index"])
            return self._status["playlist_loop"][cur_index]
        except KeyError:
            pass
        try:
            return self._status["remoteMeta"]
        except KeyError:
            pass
        return None

    @property
    def title(self):
        """Return title of current playing media."""
        if "title" in self.current_track:
            return self.current_track["title"]
        return None

    @property
    def artist(self):
        """Return artist of current playing media."""
        if "artist" in self.current_track:
            return self.current_track["artist"]
        return None

    @property
    def album(self):
        """Return album of current playing media."""
        if "album" in self.current_track:
            return self.current_track["album"]
        return None

    @property
    def shuffle(self):
        """Return shuffle mode. May be 'none, 'song', or 'album'."""
        if "playlist shuffle" in self._status:
            return SHUFFLE_MODE[self._status["playlist shuffle"]]
        return None

    @property
    def repeat(self):
        """Return repeat mode. May be 'none', 'song', or 'playlist'."""
        if "playlist repeat" in self._status:
            return REPEAT_MODE[self._status["playlist repeat"]]
        return None

    @property
    def url(self):
        """Return the url for the currently playing media."""
        if "url" in self.current_track:
            return self.current_track["url"]
        return None

    @property
    def playlist(self):
        """Return the current playlist"""
        if "playlist_loop" in self._status:
            return self._status["playlist_loop"]
        return None

    @property
    def synced(self):
        """Return true if currently synced"""
        if "sync_master" in self._status:
            return self._status["sync_master"]
        return None

    @property
    def sync_master(self):
        """Return the player id of the sync group master."""
        if "sync_master" in self._status:
            return self._status["sync_master"]
        return None

    @property
    def sync_slaves(self):
        """Return the player ids of the sync group slaves."""
        if "sync_slaves" in self._status:
            return self._status["sync_slaves"]
        return None

    @property
    def sync_group(self):
        """Return the player ids of all players in current sync group."""
        sync_group = [self.player_id]
        if self.sync_slaves:
            sync_group.append(self.sync_slaves)
        if self.sync_master:
            sync_group.append(self.sync_master)
        return sync_group

    async def async_query(self, *parameters):
        """Return result of a query specific to this player."""
        return await self._lms.async_query(*parameters, player=self._id)

    async def async_update(self):
        """
        Update the current state of the player. Return True if
        successful, False if update fails.
        """
        tags = "adKlu"
        response = await self.async_query("status", "0", "100", f"tags:{tags}")

        if response is False:
            return False

        self._status = {}
        self._status.update(response)

        return True

    async def async_set_volume(self, volume):
        """Set volume level, range 0..100, or +/- integer."""
        return await self.async_query("mixer", "volume", volume)

    async def async_set_muting(self, mute):
        """Mute (true) or unmute (false) squeezebox."""
        mute_numeric = "1" if mute else "0"
        return await self.async_query("mixer", "muting", mute_numeric)

    async def async_toggle_pause(self):
        """Send command to player to toggle play/pause."""
        return await self.async_query("pause")

    async def async_play(self):
        """Send play command to player."""
        return await self.async_query("play")

    async def async_pause(self):
        """Send pause command to player."""
        return await self.async_query("pause", "1")

    async def async_index(self, index):
        """
        Change position in playlist.

        index: if an integer, change to this position. if preceded by a + or -,
               move forward or backward this many tracks. (required)
        """
        return await self.async_query("playlist", "index", index)

    async def async_time(self, position):
        """Seek to a particular time in track."""
        return await self.async_query("time", position)

    async def async_set_power(self, power):
        """Turn on or off squeezebox."""
        if power:
            return await self.async_query("power", "1")
        return await self.async_query("power", "0")

    async def async_load_url(self, url, cmd="load"):
        """
        Play a specific track by url.

        cmd: "play" or "load" - replace current playlist (default)
        cmd: "insert" - adds next in playlist
        cmd: "add" - adds to end of playlist
        """
        return await self.async_query("playlist", cmd, url)

    async def async_load_playlist(self, playlist_ref, cmd="load"):
        """
        Play a playlist, of the sort return by the Player.playlist property.

        playlist: an array of dictionaries, which must each have a key
                  called "url." (required)
        cmd: "play" or "load" - replace current playlist (default)
        cmd: "insert" - adds next in playlist
        cmd: "add" - adds to end of playlist
        """
        success = True
        # we are going to pop the list below, so we need to copy it
        playlist = list(playlist_ref)

        if cmd == "insert":
            for item in reversed(playlist):
                if not await self.async_load_url(item["url"], cmd):
                    success = False
            return success

        if cmd in ["play", "load"]:
            if not await self.async_load_url(playlist.pop(0)["url"], "play"):
                success = False
        for item in playlist:
            if not await self.async_load_url(item["url"], "add"):
                success = False
        return success

    async def async_set_shuffle(self, shuffle):
        """Enable/disable shuffle mode."""
        if shuffle in SHUFFLE_MODE:
            shuffle_int = SHUFFLE_MODE.index(shuffle)
            return await self.async_query("playlist", "shuffle", shuffle_int)

    async def async_set_repeat(self, repeat):
        """Enable/disable repeat."""
        if repeat in REPEAT_MODE:
            repeat_int = REPEAT_MODE.index(repeat)
            return await self.async_query("playlist", "repeat", repeat_int)

    async def async_clear_playlist(self):
        """Send the media player the command for clear playlist."""
        return await self.async_query("playlist", "clear")

    async def async_sync(self, other_player):
        """
        Add another Squeezebox player to this player's sync group.

        If the other player is a member of a sync group, it will leave the
        current sync group without asking.

        Other player may be a player object, or a player_id.
        """
        if isinstance(other_player, Player):
            other_player_id = other_player.player_id
        else:
            other_player_id = other_player

        if not other_player_id:
            raise RuntimeError(
                'async_sync called without other_player or other_player_id'
            )

        return await self.async_query("sync", other_player_id)

    async def async_unsync(self):
        """Unsync this Squeezebox player."""
        return await self.async_query("sync", "-")