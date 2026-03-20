"""Stock code data fetcher for TWSE and TPEx.

This module provides functionality to fetch and process stock code information
from Taiwan Stock Exchange (TWSE) and Taipei Exchange (TPEx).
"""

import csv
import os
from collections import namedtuple

import requests
from lxml import etree

# Constants
TWSE_EQUITIES_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
TPEX_EQUITIES_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Type definitions
ROW = namedtuple(
    "Row",
    ["type", "code", "name", "ISIN", "start", "market", "group", "CFI"]
)


def make_row_tuple(typ: str, row: list[str]) -> ROW:
    """Create a ROW namedtuple from raw data.

    Args:
        typ: The type of the stock (e.g., "股票", "ETF")
        row: List of string values from the HTML table row

    Returns:
        ROW: A namedtuple containing the processed stock information

    Example:
        >>> row = ["1", "2330　台積電", "TW0002330000", "1994/09/05", "上市", "半導體業", "ESVUFR", "N/A"]
        >>> result = make_row_tuple("股票", row)
        >>> result.code
        '2330'
        >>> result.name
        '台積電'
    """
    code, name = row[1].split("\u3000")
    return ROW(typ, code, name, *row[2:-1])


def fetch_data(url: str) -> list[ROW]:
    """Fetch stock data from the specified URL.

    Args:
        url: The URL to fetch data from (TWSE or TPEx)

    Returns:
        List[ROW]: List of stock information as ROW namedtuples

    Raises:
        requests.RequestException: If the HTTP request fails
        etree.ParseError: If the HTML parsing fails
    """
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        root = etree.HTML(response.text)
        trs = root.xpath("//tr")[1:]

        result: list[ROW] = []
        current_type: str = ""
        
        for tr in trs:
            tr_data = list(map(lambda x: x.text, tr.iter()))
            if len(tr_data) == 4:
                # This is a type row
                current_type = tr_data[2].strip(" ")
            else:
                # This is a data row
                result.append(make_row_tuple(current_type, tr_data))
                
        return result
    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch data from {url}: {e!s}")
    except etree.ParseError as e:
        raise etree.ParseError(f"Failed to parse HTML from {url}: {e!s}")


def to_csv(url: str, path: str) -> None:
    """Save stock data to a CSV file.

    Args:
        url: The URL to fetch data from
        path: The path where the CSV file should be saved

    Raises:
        IOError: If the file cannot be written
    """
    try:
        data = fetch_data(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, "w", newline="", encoding="utf_8") as csvfile:
            writer = csv.writer(
                csvfile,
                delimiter=",",
                quotechar='"',
                quoting=csv.QUOTE_MINIMAL
            )
            writer.writerow(data[0]._fields)
            for row in data:
                writer.writerow([_ for _ in row])
    except OSError as e:
        raise OSError(f"Failed to write CSV file to {path}: {e!s}")


def update_stock_codes() -> tuple[str, str]:
    """Update both TWSE and TPEx stock code files.

    Returns:
        Tuple[str, str]: Paths to the created TWSE and TPEx CSV files

    Raises:
        Exception: If either file update fails
    """
    try:
        directory = os.path.dirname(os.path.abspath(__file__))
        twse_path = os.path.join(directory, "twse_equities.csv")
        tpex_path = os.path.join(directory, "tpex_equities.csv")
        
        to_csv(TWSE_EQUITIES_URL, twse_path)
        to_csv(TPEX_EQUITIES_URL, tpex_path)
        
        return twse_path, tpex_path
    except Exception as e:
        raise Exception(f"Failed to update stock codes: {e!s}")


if __name__ == "__main__":
    try:
        twse_path, tpex_path = update_stock_codes()
        print("Successfully updated stock codes:")
        print(f"- TWSE: {twse_path}")
        print(f"- TPEx: {tpex_path}")
    except Exception as e:
        print(f"Error: {e!s}")
        exit(1)