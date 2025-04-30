from enum import Enum


class ReportTypes(Enum):
    BOOKING = "booking"
    FREQUENCY = "frequency"
    POD_AGENT = "pod_agent"

    @classmethod
    def get_list(cls) -> list[str]:
        return [report_type.value for report_type in cls]
