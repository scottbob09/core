"""Support for Tuya LaView Trackers."""
from __future__ import annotations

from typing import Any

from tuya_iot import TuyaDevice, TuyaDeviceManager

from homeassistant.components.tracker import (

)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_IDLE, STATE_PAUSED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomeAssistantTuyaData
from .base import EnumTypeData, IntegerTypeData, TuyaEntity
from .const import DOMAIN, TUYA_DISCOVERY_NEW, DPCode, DPType

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Tuya tracker dynamically through Tuya discovery."""
    hass_data: HomeAssistantTuyaData = hass.data[DOMAIN][entry.entry_id]

    @callback
    def async_discover_device(device_ids: list[str]) -> None:
        """Discover and add a discovered Tuya tracker."""
        entities: list[TuyaTrackerEntity] = []
        for device_id in device_ids:
            device = hass_data.device_manager.device_map[device_id]
            if device.category == "tracker":
                entities.append(TuyaTrackerEntity(device, hass_data.device_manager))
        async_add_entities(entities)

    async_discover_device([*hass_data.device_manager.device_map])

    entry.async_on_unload(
        async_dispatcher_connect(hass, TUYA_DISCOVERY_NEW, async_discover_device)
    )


class TuyaTrackerEntity(TuyaEntity, StateTrackerEntity):
    """Tuya Tracker Device."""
    """Below is mostly still vacuum template......."""
    
    _battery_level: IntegerTypeData | None = None

    def __init__(self, device: TuyaDevice, device_manager: TuyaDeviceManager) -> None:
        """Init Tuya vacuum."""
        super().__init__(device, device_manager)

        self._attr_fan_speed_list = []

        self._attr_supported_features |= VacuumEntityFeature.SEND_COMMAND
        if self.find_dpcode(DPCode.PAUSE, prefer_function=True):
            self._attr_supported_features |= VacuumEntityFeature.PAUSE

        if self.find_dpcode(DPCode.SWITCH_CHARGE, prefer_function=True):
            self._attr_supported_features |= VacuumEntityFeature.RETURN_HOME
        elif (
            enum_type := self.find_dpcode(
                DPCode.MODE, dptype=DPType.ENUM, prefer_function=True
            )
        ) and TUYA_MODE_RETURN_HOME in enum_type.range:
            self._attr_supported_features |= VacuumEntityFeature.RETURN_HOME

        if self.find_dpcode(DPCode.FINDDEV, prefer_function=False):
            self._attr_supported_features |= TrackerEntityFeature.FINDDEV

        if self.find_dpcode(DPCode.STATUS, prefer_function=True):
            self._attr_supported_features |= (
                VacuumEntityFeature.STATE | VacuumEntityFeature.STATUS
            )

        if self.find_dpcode(DPCode.POWER, prefer_function=True):
            self._attr_supported_features |= (
                VacuumEntityFeature.TURN_ON | VacuumEntityFeature.TURN_OFF
            )

        if self.find_dpcode(DPCode.POWER_GO, prefer_function=True):
            self._attr_supported_features |= (
                VacuumEntityFeature.STOP | VacuumEntityFeature.START
            )

        if enum_type := self.find_dpcode(
            DPCode.TRMODE, dptype=DPType.ENUM, prefer_function=True
        ):
            self._tracking_mode = enum_type
            self._attr_tracking_mode = enum_type.range
            self._attr_supported_features |= TrackingEntityFeature.TRMODE

        if int_type := self.find_dpcode(DPCode.ELECTRICITY_LEFT, dptype=DPType.INTEGER):
            self._attr_supported_features |= VacuumEntityFeature.BATTERY
            self._battery_level = int_type

    @property
    def battery_level(self) -> int | None:
        """Return Tuya device state."""
        if self._battery_level is None or not (
            status := self.device.status.get(DPCode.ELECTRICITY_LEFT)
        ):
            return None
        return round(self._battery_level.scale_value(status))

    @property
    def tracking_mode(self) -> str | None:
        """Return the tracking aggressiveness"""
        return self.device.status.get(DPCode.TRMODE)

    @property
    def state(self) -> str | None:
        """Return Tuya tracker SOS state."""
        if self.device.status.get(DPCode.PAUSE) and not (
            self.device.status.get(DPCode.STATUS)
        ):
            return STATE_PAUSED
        if not (status := self.device.status.get(DPCode.STATUS)):
            return None
        return TUYA_STATUS_TO_HA.get(status)

    def turn_on(self, **kwargs: Any) -> None:
        """Turn the device on."""
        self._send_command([{"code": DPCode.POWER, "value": True}])

    def turn_off(self, **kwargs: Any) -> None:
        """Turn the device off."""
        self._send_command([{"code": DPCode.POWER, "value": False}])

    def start(self, **kwargs: Any) -> None:
        """Start the device."""
        self._send_command([{"code": DPCode.POWER_GO, "value": True}])

    def stop(self, **kwargs: Any) -> None:
        """Stop the device."""
        self._send_command([{"code": DPCode.POWER_GO, "value": False}])

    def pause(self, **kwargs: Any) -> None:
        """Pause the device."""
        self._send_command([{"code": DPCode.POWER_GO, "value": False}])

    def return_to_base(self, **kwargs: Any) -> None:
        """Return device to dock."""
        self._send_command(
            [
                {"code": DPCode.SWITCH_CHARGE, "value": True},
                {"code": DPCode.MODE, "value": TUYA_MODE_RETURN_HOME},
            ]
        )

    def locate(self, **kwargs: Any) -> None:
        """Locate the device."""
        self._send_command([{"code": DPCode.FINDDEV, "value": True}])

    def set_tracking_mode(self, tracking_mode: str, **kwargs: Any) -> None:
        """Set tracker mode."""
        self._send_command([{"code": DPCode.TRMODE, "value": tracking_mode}])

    def send_command(
        self, command: str, params: dict | list | None = None, **kwargs: Any
    ) -> None:
        """Send raw command."""
        if not params:
            raise ValueError("Params cannot be omitted for Tuya tracker commands")
        self._send_command([{"code": command, "value": params[0]}])
