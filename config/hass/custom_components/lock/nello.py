"""
Nello.io lock platform.

For more details about this platform, please refer to the documentation
https://home-assistant.io/components/lock.nello/
"""
import asyncio
from itertools import filterfalse
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.http import HomeAssistantView
from homeassistant.components.http.const import KEY_REAL_IP
from homeassistant.components.lock import (LockDevice, PLATFORM_SCHEMA)
from homeassistant.const import (
    CONF_PASSWORD, CONF_USERNAME, HTTP_BAD_REQUEST)


REQUIREMENTS = ['pynello==1.5.1']

_LOGGER = logging.getLogger(__name__)

ATTR_ADDRESS = 'address'
ATTR_LOCATION_ID = 'location_id'
EVENT_DOOR_BELL = 'nello_bell_ring'
NELLO_HANDLER_URL = '/api/nello_webhooks'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Nello lock platform."""
    from pynello import Nello
    nello = Nello(config.get(CONF_USERNAME), config.get(CONF_PASSWORD))
    add_devices([NelloLock(lock) for lock in nello.locations], True)
    hass.http.register_view(NelloCloudPushReceiver())


class NelloLock(LockDevice):
    """Representation of a Nello lock."""

    def __init__(self, nello_lock):
        """Initialize the lock."""
        self._nello_lock = nello_lock
        self._device_attrs = None
        self._activity = None
        self._name = None

    @property
    def name(self):
        """Return the name of the lock."""
        return self._name

    @property
    def is_locked(self):
        """Return true if lock is locked."""
        return True

    @property
    def device_state_attributes(self):
        """Return the device specific state attributes."""
        return self._device_attrs

    def update(self):
        """Update the nello lock properties."""
        self._nello_lock.update()
        # Location identifiers
        location_id = self._nello_lock.location_id
        short_id = self._nello_lock.short_id
        address = self._nello_lock.address
        self._name = 'Nello {}'.format(short_id)
        self._device_attrs = {
            ATTR_ADDRESS: address,
            ATTR_LOCATION_ID: location_id
        }
        # Process recent activity
        activity = self._nello_lock.activity
        if self._activity:
            # Filter out old events
            new_activity = list(
                filterfalse(lambda x: x in self._activity, activity))
            if new_activity:
                for act in new_activity:
                    activity_type = act.get('type')
                    if activity_type == 'bell.ring.denied':
                        event_data = {
                            'address': address,
                            'date': act.get('date'),
                            'description': act.get('description'),
                            'location_id': location_id,
                            'short_id': short_id
                        }
                        self.hass.bus.fire(EVENT_DOOR_BELL, event_data)
        # Save the activity history so that we don't trigger an event twice
        self._activity = activity

    def unlock(self, **kwargs):
        """Unlock the device."""
        if not self._nello_lock.open_door():
            _LOGGER.error("Failed to unlock")


class NelloCloudPushReceiver(HomeAssistantView):
    """Handle cloud push event from nello."""

    requires_auth = False
    url = NELLO_HANDLER_URL
    name = 'nello_webhooks'

    @asyncio.coroutine
    def put(self, request):
        """Accept PUT messages from nello."""
        hass = request.app["hass"]
        json_data = yield from request.json()
        data = dict(json_data)
        action = json_data.get("action")
        extra_data = json_data.get("data")
        if action == "deny":
            hass.bus.async_fire("nello_ring", extra_data)
        elif action == "swipe":
            hass.bus.async_fire("nello_open", extra_data)
        elif action == "tw":
            hass.bus.async_fire("nello_time_window", extra_data)
        elif action == "geo":
            hass.bus.async_fire("nello_geo", extra_data)
        else:
            hass.bus.async_fire("nello_event", data)
        _LOGGER.critical("Received message from nello: %s", data)
