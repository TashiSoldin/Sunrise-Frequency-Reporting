from enum import Enum


class LastEventTypes(Enum):
    ATTEMPTED_DELIVERY = "Attempted delivery"
    ATTEMPTED_MISROUTE = "Attempted Misroute"
    CHAIN_STORE_FLOOR_CHECK = "Chain store floor check"
    CHECKED_IN_AT_ORIGIN_DEPOT = "Checked in at Origin Depot"
    CONSIGNMENT_DETAILS_CAPTURED = "Consignment details captured"
    CUSTOMER_QUERY_FLOOR_CHECK = "Customer query floor check"
    EVENT_SCAN_BLOCKED = "Event Scan Blocked"
    FLOOR_CHECK = "Floor check"
    FLOOR_CHECK_BOOKING_CARGO = "Floor check - Booking cargo"
    FLOOR_CHECK_DEPOT_COLLECTION = "Floor check - Depot collection"
    FLOOR_CHECK_QUERY = "Floor check - Query"
    INBOUND_MANIFEST = "Inbound Manifest"
    LOADED_FOR_DELIVERY = "Loaded for Delivery"
    MANIFEST_TRANSFERRED = "Manifest Transferred"
    MIS_ROUTED = "Mis-routed"
    OUTBOUND_MANIFEST_LOAD = "Outbound Manifest Load"
    POD_DETAILS_CAPTURED = "POD Details Captured"
    POD_IMAGE_SCANNED = "POD Image Scanned"
    PRELOAD = "Preload"
    RECEIVED_AT_ORIGIN_DEPOT = "Received at origin depot"
    REMOVE_FROM_MANIFEST_TRIPSHEET = "Remove from manifest/tripsheet"
    RETURN_TO_CLIENT = "Return to Client"
    RETURN_TO_DEPOT = "Return to Depot"
    REVERSE_LOGISTICS_FLOOR_CHECK = "Reverse logistics floor check"
    SWADDED = "Swadded"
    TRANSFER_TO_MANIFEST_TRIPSHEET = "Transfer to manifest/tripsheet"
    UNLOAD_MANIFEST_TRIPSHEET = "Unload manifest/tripsheet"

    @classmethod
    def get_ordered_values(cls) -> list:
        """Returns list of enum values in the specified sort order"""
        return [
            cls.FLOOR_CHECK_DEPOT_COLLECTION.value,
            cls.LOADED_FOR_DELIVERY.value,
            cls.ATTEMPTED_DELIVERY.value,
            cls.ATTEMPTED_MISROUTE.value,
            cls.MIS_ROUTED.value,
            cls.CUSTOMER_QUERY_FLOOR_CHECK.value,
            cls.RETURN_TO_CLIENT.value,
            cls.RETURN_TO_DEPOT.value,
            cls.FLOOR_CHECK_QUERY.value,
            cls.REVERSE_LOGISTICS_FLOOR_CHECK.value,
            cls.RECEIVED_AT_ORIGIN_DEPOT.value,
            cls.CHECKED_IN_AT_ORIGIN_DEPOT.value,
            cls.CONSIGNMENT_DETAILS_CAPTURED.value,
            cls.FLOOR_CHECK.value,
            cls.SWADDED.value,
            cls.MANIFEST_TRANSFERRED.value,
            cls.TRANSFER_TO_MANIFEST_TRIPSHEET.value,
            cls.UNLOAD_MANIFEST_TRIPSHEET.value,
            cls.INBOUND_MANIFEST.value,
            cls.REMOVE_FROM_MANIFEST_TRIPSHEET.value,
            cls.EVENT_SCAN_BLOCKED.value,
            cls.PRELOAD.value,
            cls.OUTBOUND_MANIFEST_LOAD.value,
            cls.FLOOR_CHECK_BOOKING_CARGO.value,
            cls.CHAIN_STORE_FLOOR_CHECK.value,
            cls.POD_DETAILS_CAPTURED.value,
            cls.POD_IMAGE_SCANNED.value,
        ]


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
