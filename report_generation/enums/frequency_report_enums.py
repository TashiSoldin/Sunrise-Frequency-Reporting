from enum import Enum

class LastEventStatusColors(Enum):
    LOADED_FOR_DELIVERY = "#00aeed"                 # Blue
    POD_DETAILS_CAPTURED = "#d0e833"                # Green
    POD_IMAGE_SCANNED = "#d0e833"
    ATTEMPTED_DELIVERY = "#f7bc00"                  # Orange
    CHECKED_IN_AT_ORIGIN_DEPOT = "#f7bc00"
    CONSIGNMENT_DETAILS_CAPTURED = "#f7bc00"
    EVENT_SCAN_BLOCKED = "#f7bc00"
    FLOOR_CHECK = "#f7bc00"
    INBOUND_MANIFEST = "#f7bc00"
    MANIFEST_TRANSFERRED = "#f7bc00"
    MIS_ROUTED = "#f7bc00"
    RECEIVED_AT_ORIGIN_DEPOT = "#f7bc00"
    REMOVE_FROM_MANIFEST_TRIPSHEET = "#f7bc00"
    RETURN_TO_CLIENT = "#f7bc00"
    RETURN_TO_DEPOT = "#f7bc00"
    REVERSE_LOGISTICS_FLOOR_CHECK = "#f7bc00"
    SWADDED = "#f7bc00"
    UNLOAD_MANIFEST_TRIPSHEET = "#f7bc00"
    FLOOR_CHECK_DEPOT_COLLECTION = "#eac7e6"        # Purple
    CHAIN_STORE_FLOOR_CHECK = "#fdf900"             # Yellow
    FLOOR_CHECK_BOOKING_CARGO = "#fdf900"
    OUTBOUND_MANIFEST_LOAD = "#fdf900"
    OTHER = "White"                                 # Default color

    @classmethod
    def get_event_color(cls, event: str) -> str:
        """Retrieve the color associated with an event name."""
        event_key = event.replace(" ", "_").upper()  # Format event to match Enum member name
        return getattr(cls, event_key, cls.OTHER).value

# # Example usage
# event = 'Loaded for Delivery'
# color = LastEventStatusColors.get_event_color(event)
# print(f"The color for '{event}' is {color}.")
