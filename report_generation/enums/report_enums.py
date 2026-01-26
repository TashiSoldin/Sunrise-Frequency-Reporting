from enum import Enum


class ReportTypes(Enum):
    BOOKING = "booking"
    FREQUENCY = "frequency"
    FREQUENCY_NLE = "frequency_nle"
    POD_AGENT = "pod_agent"
    POD_OCD = "pod_ocd"
    POD_SUMMARY = "pod_summary"
    POD_SUMMARY_PYTD = "pod_summary_pytd"
    CHAMPION = "champion"

    @classmethod
    def get_list(cls) -> list[str]:
        return [report_type.value for report_type in cls]
