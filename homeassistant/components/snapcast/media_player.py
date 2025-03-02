"""Support for interacting with Snapcast clients."""
from __future__ import annotations

import logging
import socket

import snapcast.control
from snapcast.control.server import CONTROL_PORT
import voluptuous as vol

from homeassistant.components.media_player import (
    PLATFORM_SCHEMA,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    ATTR_LATENCY,
    ATTR_MASTER,
    CLIENT_PREFIX,
    CLIENT_SUFFIX,
    DATA_KEY,
    GROUP_PREFIX,
    GROUP_SUFFIX,
    SERVICE_JOIN,
    SERVICE_RESTORE,
    SERVICE_SET_LATENCY,
    SERVICE_SNAPSHOT,
    SERVICE_UNJOIN,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Required(CONF_HOST): cv.string, vol.Optional(CONF_PORT): cv.port}
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Snapcast platform."""

    host = config.get(CONF_HOST)
    port = config.get(CONF_PORT, CONTROL_PORT)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(SERVICE_SNAPSHOT, {}, "snapshot")
    platform.async_register_entity_service(SERVICE_RESTORE, {}, "async_restore")
    platform.async_register_entity_service(
        SERVICE_JOIN, {vol.Required(ATTR_MASTER): cv.entity_id}, handle_async_join
    )
    platform.async_register_entity_service(SERVICE_UNJOIN, {}, handle_async_unjoin)
    platform.async_register_entity_service(
        SERVICE_SET_LATENCY,
        {vol.Required(ATTR_LATENCY): cv.positive_int},
        handle_set_latency,
    )

    try:
        server = await snapcast.control.create_server(
            hass.loop, host, port, reconnect=True
        )
    except socket.gaierror:
        _LOGGER.error("Could not connect to Snapcast server at %s:%d", host, port)
        return

    # Note: Host part is needed, when using multiple snapservers
    hpid = f"{host}:{port}"

    devices: list[MediaPlayerEntity] = [
        SnapcastGroupDevice(group, hpid) for group in server.groups
    ]
    devices.extend(SnapcastClientDevice(client, hpid) for client in server.clients)
    hass.data[DATA_KEY] = devices
    async_add_entities(devices)


async def handle_async_join(entity, service_call):
    """Handle the entity service join."""
    if not isinstance(entity, SnapcastClientDevice):
        raise TypeError("Entity is not a client. Can only join clients.")
    await entity.async_join(service_call.data[ATTR_MASTER])


async def handle_async_unjoin(entity, service_call):
    """Handle the entity service unjoin."""
    if not isinstance(entity, SnapcastClientDevice):
        raise TypeError("Entity is not a client. Can only unjoin clients.")
    await entity.async_unjoin()


async def handle_set_latency(entity, service_call):
    """Handle the entity service set_latency."""
    if not isinstance(entity, SnapcastClientDevice):
        raise TypeError("Latency can only be set for a Snapcast client.")
    await entity.async_set_latency(service_call.data[ATTR_LATENCY])


class SnapcastGroupDevice(MediaPlayerEntity):
    """Representation of a Snapcast group device."""

    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, group, uid_part):
        """Initialize the Snapcast group device."""
        self._group = group
        self._uid = f"{GROUP_PREFIX}{uid_part}_{self._group.identifier}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to group events."""
        self._group.set_callback(self.schedule_update_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect group object when removed."""
        self._group.set_callback(None)

    @property
    def state(self) -> MediaPlayerState | None:
        """Return the state of the player."""
        return {
            "idle": MediaPlayerState.IDLE,
            "playing": MediaPlayerState.PLAYING,
            "unknown": None,
        }.get(self._group.stream_status)

    @property
    def unique_id(self):
        """Return the ID of snapcast group."""
        return self._uid

    @property
    def name(self):
        """Return the name of the device."""
        return f"{GROUP_PREFIX}{self._group.identifier}"

    @property
    def source(self):
        """Return the current input source."""
        return self._group.stream

    @property
    def volume_level(self):
        """Return the volume level."""
        return self._group.volume / 100

    @property
    def is_volume_muted(self):
        """Volume muted."""
        return self._group.muted

    @property
    def source_list(self):
        """List of available input sources."""
        return list(self._group.streams_by_name().keys())

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        name = f"{self._group.friendly_name} {GROUP_SUFFIX}"
        return {"friendly_name": name}

    async def async_select_source(self, source: str) -> None:
        """Set input source."""
        streams = self._group.streams_by_name()
        if source in streams:
            await self._group.set_stream(streams[source].identifier)
            self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Send the mute command."""
        await self._group.set_muted(mute)
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level."""
        await self._group.set_volume(round(volume * 100))
        self.async_write_ha_state()

    def snapshot(self):
        """Snapshot the group state."""
        self._group.snapshot()

    async def async_restore(self):
        """Restore the group state."""
        await self._group.restore()
        self.async_write_ha_state()


class SnapcastClientDevice(MediaPlayerEntity):
    """Representation of a Snapcast client device."""

    _attr_should_poll = False
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, client, uid_part):
        """Initialize the Snapcast client device."""
        self._client = client
        self._uid = f"{CLIENT_PREFIX}{uid_part}_{self._client.identifier}"

    async def async_added_to_hass(self) -> None:
        """Subscribe to client events."""
        self._client.set_callback(self.schedule_update_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Disconnect client object when removed."""
        self._client.set_callback(None)

    @property
    def unique_id(self):
        """
        Return the ID of this snapcast client.

        Note: Host part is needed, when using multiple snapservers
        """
        return self._uid

    @property
    def identifier(self):
        """Return the snapcast identifier."""
        return self._client.identifier

    @property
    def name(self):
        """Return the name of the device."""
        return f"{CLIENT_PREFIX}{self._client.identifier}"

    @property
    def source(self):
        """Return the current input source."""
        return self._client.group.stream

    @property
    def volume_level(self):
        """Return the volume level."""
        return self._client.volume / 100

    @property
    def is_volume_muted(self):
        """Volume muted."""
        return self._client.muted

    @property
    def source_list(self):
        """List of available input sources."""
        return list(self._client.group.streams_by_name().keys())

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the player."""
        if self._client.connected:
            return MediaPlayerState.ON
        return MediaPlayerState.OFF

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        state_attrs = {}
        if self.latency is not None:
            state_attrs["latency"] = self.latency
        name = f"{self._client.friendly_name} {CLIENT_SUFFIX}"
        state_attrs["friendly_name"] = name
        return state_attrs

    @property
    def latency(self):
        """Latency for Client."""
        return self._client.latency

    async def async_select_source(self, source: str) -> None:
        """Set input source."""
        streams = self._client.group.streams_by_name()
        if source in streams:
            await self._client.group.set_stream(streams[source].identifier)
            self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        """Send the mute command."""
        await self._client.set_muted(mute)
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume level."""
        await self._client.set_volume(round(volume * 100))
        self.async_write_ha_state()

    async def async_join(self, master):
        """Join the group of the master player."""

        master_entity = next(
            entity for entity in self.hass.data[DATA_KEY] if entity.entity_id == master
        )
        if not isinstance(master_entity, SnapcastClientDevice):
            raise TypeError("Master is not a client device. Can only join clients.")

        master_group = next(
            group
            for group in self._client.groups_available()
            if master_entity.identifier in group.clients
        )
        await master_group.add_client(self._client.identifier)
        self.async_write_ha_state()

    async def async_unjoin(self):
        """Unjoin the group the player is currently in."""
        await self._client.group.remove_client(self._client.identifier)
        self.async_write_ha_state()

    def snapshot(self):
        """Snapshot the client state."""
        self._client.snapshot()

    async def async_restore(self):
        """Restore the client state."""
        await self._client.restore()
        self.async_write_ha_state()

    async def async_set_latency(self, latency):
        """Set the latency of the client."""
        await self._client.set_latency(latency)
        self.async_write_ha_state()
