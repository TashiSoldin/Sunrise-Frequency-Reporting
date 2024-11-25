import os
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Font, Border, Side, PatternFill
import pandas as pd


class ExcelHelper:
    def __init__(self, asset_file_path: str):
        self.asset_file_path = asset_file_path
        self.color_mapping = {
            "Attempted delivery": "f7bc00",
            "Attempted Misroute": "f7bc00",
            "Chain store floor check": "fdf900",
            "Checked in at Origin Depot": "f7bc00",
            "Consignment details captured": "f7bc00",
            "Customer query floor check": "f7bc00",
            "Event Scan Blocked": "f7bc00",
            "Floor check": "f7bc00",
            "Floor check - Booking cargo": "fdf900",
            "Floor check - Depot collection": "eac7e6",
            "Floor check - Query": "f7bc00",
            "Inbound Manifest": "f7bc00",
            "Loaded for Delivery": "00aeed",
            "Manifest Transferred": "f7bc00",
            "Mis-routed": "f7bc00",
            "Outbound Manifest Load": "fdf900",
            "POD Details Captured": "92d050",
            "POD Image Scanned": "92d050",
            "Preload": "fdf900",
            "Received at origin depot": "f7bc00",
            "Remove from manifest/tripsheet": "f7bc00",
            "Return to Client": "f7bc00",
            "Return to Depot": "f7bc00",
            "Reverse logistics floor check": "f7bc00",
            "Swadded": "f7bc00",
            "Transfer to manifest/tripsheet": "f7bc00",
            "Unload manifest/tripsheet": "f7bc00",
            "Other": "FFFFFF",
        }

    def load_template(self, template_name: str) -> str:
        template_path = os.path.join(self.asset_file_path, template_name)
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found at {template_path}")
        return template_path

    def append_df_to_sheet(self, worksheet, df: pd.DataFrame, start_row: int) -> None:
        thin = Side(border_style="thin", color="000000")
        border = Border(top=thin, left=thin, right=thin, bottom=thin)
        last_event_col_index = df.columns.get_loc("Last Event")

        for r_idx, row in enumerate(
            dataframe_to_rows(df, index=False, header=True), start=start_row
        ):
            for c_idx, value in enumerate(row, 1):
                cell = worksheet.cell(row=r_idx, column=c_idx, value=value)
                if r_idx == start_row:
                    cell.font = Font(bold=True)
                    cell.border = border

            if r_idx > start_row:
                last_event = row[last_event_col_index]
                color = self.color_mapping.get(last_event, "FFFFFF")
                for c_idx in range(1, len(row) + 1):
                    cell_to_style = worksheet.cell(row=r_idx, column=c_idx)
                    cell_to_style.fill = PatternFill(
                        start_color=color, end_color=color, fill_type="solid"
                    )

    def update_template_placeholders(self, workbook, replacements: dict) -> None:
        for sheet in workbook.sheetnames:
            ws = workbook[sheet]
            for row in ws.iter_rows():
                for cell in row:
                    if cell.value in replacements:
                        cell.value = replacements[cell.value]
