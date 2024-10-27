from enum import Enum


class LastEventTypes(Enum):
    LOADED_FOR_DELIVERY = "Loaded for Delivery"
    POD_DETAILS_CAPTURED = "POD Details Captured"
    POD_IMAGE_SCANNED = "POD Image Scanned"
    ATTEMPTED_DELIVERY = "Attempted Delivery"
    CHECKED_IN_AT_ORIGIN_DEPOT = "Checked in at Origin Depot"
    CONSIGNMENT_DETAILS_CAPTURED = "Consignment Details Captured"
    EVENT_SCAN_BLOCKED = "Event Scan Blocked"
    FLOOR_CHECK = "Floor Check"
    INBOUND_MANIFEST = "Inbound Manifest"
    MANIFEST_TRANSFERRED = "Manifest Transferred"
    MIS_ROUTED = "Mis Routed"
    RECEIVED_AT_ORIGIN_DEPOT = "Received at Origin Depot"
    REMOVE_FROM_MANIFEST_TRIPSHEET = "Remove from Manifest Tripsheet"
    RETURN_TO_CLIENT = "Return to Client"
    RETURN_TO_DEPOT = "Return to Depot"
    REVERSE_LOGISTICS_FLOOR_CHECK = "Reverse Logistics Floor Check"
    SWADDED = "Swadded"
    UNLOAD_MANIFEST_TRIPSHEET = "Unload Manifest Tripsheet"
    FLOOR_CHECK_DEPOT_COLLECTION = "Floor Check Depot Collection"
    CHAIN_STORE_FLOOR_CHECK = "Chain Store Floor Check"
    FLOOR_CHECK_BOOKING_CARGO = "Floor Check Booking Cargo"
    OUTBOUND_MANIFEST_LOAD = "Outbound Manifest Load"


class LastEventStyles(Enum):
    LOADED_FOR_DELIVERY = {"color": "#00aeed"}
    POD_DETAILS_CAPTURED = {"color": "#d0e833"}
    POD_IMAGE_SCANNED = {"color": "#d0e833"}
    ATTEMPTED_DELIVERY = {"color": "#f7bc00"}
    CHECKED_IN_AT_ORIGIN_DEPOT = {"color": "#f7bc00"}
    CONSIGNMENT_DETAILS_CAPTURED = {"color": "#f7bc00"}
    EVENT_SCAN_BLOCKED = {"color": "#f7bc00"}
    FLOOR_CHECK = {"color": "#f7bc00"}
    INBOUND_MANIFEST = {"color": "#f7bc00"}
    MANIFEST_TRANSFERRED = {"color": "#f7bc00"}
    MIS_ROUTED = {"color": "#f7bc00"}
    RECEIVED_AT_ORIGIN_DEPOT = {"color": "#f7bc00"}
    REMOVE_FROM_MANIFEST_TRIPSHEET = {"color": "#f7bc00"}
    RETURN_TO_CLIENT = {"color": "#f7bc00"}
    RETURN_TO_DEPOT = {"color": "#f7bc00"}
    REVERSE_LOGISTICS_FLOOR_CHECK = {"color": "#f7bc00"}
    SWADDED = {"color": "#f7bc00"}
    UNLOAD_MANIFEST_TRIPSHEET = {"color": "#f7bc00"}
    FLOOR_CHECK_DEPOT_COLLECTION = {"color": "#eac7e6"}
    CHAIN_STORE_FLOOR_CHECK = {"color": "#fdf900"}
    FLOOR_CHECK_BOOKING_CARGO = {"color": "#fdf900"}
    OUTBOUND_MANIFEST_LOAD = {"color": "#fdf900"}
    OTHER = {"color": "#ffffff"}

    @classmethod
    def get_event_style(cls, event: str) -> dict:
        """Retrieve the style dictionary associated with an event name."""
        event_key = event.replace(" ", "_").upper()
        return getattr(cls, event_key, cls.OTHER).value
