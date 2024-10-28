import pandas as pd

# from report_generation.enums.frequency_report_enums import LastEventStyles


class StyleHelper:
    """Helper class for applying styles to DataFrames."""

    @staticmethod
    def color_rows(row: pd.Series) -> list[str]:
        """
        Apply background color to an entire row based on the 'Last Event' value.

        Args:
            row: A pandas Series representing a row in the DataFrame

        Returns:
            list: A list of style dictionaries for each cell in the row
        """
        # Get the style dictionary for the Last Event
        style = LastEventStyles.get_event_style(row["Last Event"])

        # Create a background-color style for each cell in the row
        return [f"background-color: {style['color']}"] * len(row)
