#!/usr/bin/python
#
# reference rstats.c TomatoUsb source code
#
#
#    Copyright (C) 2010 - 2015 VREM Software Development <VREMSoftwareDevelopment@gmail.com>
#    Copyright (C) 2023 Alex Wiser <https://github.com/awsr>
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
#


from abc import abstractmethod
import argparse
import gzip
import json
import math
import struct
import subprocess
import sys
import traceback
from datetime import datetime
from os.path import isfile
from shutil import copyfile


# Constants
LOG_FORMAT_VER = 2
PETABYTE = math.pow(1024, 5)
DATE_FORMAT = "%Y-%m-%d"


def get_time(file: str | None = None):
    try:
        if file is not None:
            local_time = subprocess.run(
                ["date", "-Iseconds", "-r", file], check=True, capture_output=True
            )
        else:
            local_time = subprocess.run(
                ["date", "-Iseconds"], check=True, capture_output=True
            )
        return datetime.fromisoformat(local_time.stdout.decode("utf8").split("\n")[0])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return datetime.now()


NOW = get_time()


# fmt: off
_data_scale = {
    'kb': 1, 'kib': 1,
    'mb': 2, 'mib': 2,
    'gb': 3, 'gib': 3,
    'tb': 4, 'tib': 4,
    'pb': 5, 'pib': 5,
    'eb': 6, 'eib': 6
}
# Technically kebibyte, mebibyte, gibibyte, etc...
_data_scale_names = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB')
# fmt: on


def format_bytes(size: int, scale: str | None = None) -> str:
    if size < 1024:
        return f"{size} B"

    if scale is not None:
        scale = scale.lower()

    if scale is None or scale not in _data_scale:
        exponent = int(math.floor(math.log(size, 1024)))
    else:
        exponent = _data_scale[scale]

    divisor = math.pow(1024, exponent)
    value = round(size / divisor, 2)
    return f"{value} {_data_scale_names[exponent]}"


class TrafficData:
    def __init__(
        self, date: datetime, traffic: list[int], error: list[bool] = None, misc=None
    ):
        self.date = date
        self.traffic = {
            "down": -1 if traffic[0] > PETABYTE else traffic[0],
            "up": -1 if traffic[1] > PETABYTE else traffic[1],
        }
        if error is None:
            self.error = {
                "down": self.traffic["down"] == -1,
                "up": self.traffic["up"] == -1,
            }
        else:
            self.error = {"down": error[0], "up": error[1]}
        self.misc = misc

    @property
    @abstractmethod
    def date_str(self):
        return

    def merge(self, data):
        self.traffic["down"] = max(self.traffic["down"], data["traffic"][0])
        self.traffic["up"] = max(self.traffic["up"], data["traffic"][1])

        self.error["down"] = self.error["down"] or data["error"][0]
        self.error["up"] = self.error["up"] or data["error"][1]

        if "misc" in data:
            if self.misc is None:
                self.misc = {}
            for k, v in data["misc"].items():
                self.misc[k] = v

    def export(self):
        exportable = {
            "date": self.date_str,
            "traffic": [self.traffic["down"], self.traffic["up"]],
            "error": [self.error["down"], self.error["up"]],
        }

        if self.misc is not None and len(self.misc) > 0:
            exportable["misc"] = self.misc

        return exportable

    def __str__(self) -> str:
        return (
            f"{self.date_str}: "
            + f"{format_bytes(self.traffic['down'])}, "
            + f"{format_bytes(self.traffic['up'])}"
        )


class DailyTraffic(TrafficData):
    def __init__(
        self,
        date: datetime | str,
        traffic: list[int],
        error: list[bool] = None,
        misc=None,
    ):
        if isinstance(date, str):
            date = datetime.strptime(date, DATE_FORMAT)
        super().__init__(date, traffic, error, misc)

    @property
    def date_str(self):
        return self.date.strftime(DATE_FORMAT)


class MonthlyTraffic(TrafficData):
    def __init__(
        self,
        date: datetime | str,
        traffic: list[int],
        error: list[bool] = None,
        misc=None,
    ):
        if isinstance(date, str):
            date = datetime.strptime(date, DATE_FORMAT)
            # Month entries should always be the first day of the month
            date = date.replace(day=1)
        super().__init__(date, traffic, error, misc)

    @property
    def date_str(self):
        return self.date.strftime(DATE_FORMAT)


class StatsData:
    def __init__(self, modified: datetime) -> None:
        self.daily: dict[str, DailyTraffic] = {}
        self.monthly: dict[str, MonthlyTraffic] = {}
        self.modified_time = modified

    def export(self) -> dict:
        return {
            "meta": {
                "format": LOG_FORMAT_VER,
                "time_data": self.modified_time.isoformat(),
                "time_script": NOW.isoformat(),
            },
            "daily": sorted(list(self.daily.values()), key=lambda entry: entry.date),
            "monthly": sorted(
                list(self.monthly.values()), key=lambda entry: entry.date
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.export(), default=self._default_func)

    def _default_func(self, obj):
        try:
            return obj.export()
        except Exception as e:
            raise TypeError(f"Unable to serialize {obj} of type {type(obj)}") from e

    def add_daily(self, entry: tuple[datetime, int, int]):
        new_data = DailyTraffic(entry[0], [entry[1], entry[2]])
        self.daily[new_data.date_str] = new_data

    def add_monthly(self, entry: tuple[datetime, int, int]):
        new_data = MonthlyTraffic(entry[0], [entry[1], entry[2]])
        self.monthly[new_data.date_str] = new_data

    def merge_history(self, history):
        # Previous data loaded as normal dict
        if "daily" in history:
            for previous in history["daily"]:
                prev_date = previous["date"]
                # Use old data to fill in history and roll back errors
                if prev_date in self.daily:
                    self.daily[prev_date].merge(previous)
                else:
                    self.daily[prev_date] = DailyTraffic(**previous)

        if "monthly" in history:
            for previous in history["monthly"]:
                prev_date = previous["date"]
                # Use old data to fill in history and roll back errors
                if prev_date in self.monthly:
                    self.monthly[prev_date].merge(previous)
                else:
                    self.monthly[prev_date] = MonthlyTraffic(**previous)


# rstats supports version ID_V1
class RStats:
    # expected file size in bytes
    EXPECTED_SIZE = 2112
    # version 0 has 12 entries per month
    ID_V0 = 0x30305352
    # version1 has 25 entries per month
    ID_V1 = 0x31305352

    MONTH_COUNT = 25
    DAY_COUNT = 62

    def __init__(self, filename: str, modified: datetime):
        try:
            print(">>>>>>>>>> Tomato USB RSTATS <<<<<<<<<<")
            if filename.endswith("gz"):
                with gzip.open(filename, "rb") as file_handle:
                    self.file_content = file_handle.read()
            else:
                with open(filename, "rb") as file_handle:
                    self.file_content = file_handle.read()

            filesize = len(self.file_content)
            if filesize != RStats.EXPECTED_SIZE:
                print(
                    "Unsupported file format.\n"
                    + f"Expected a size of {RStats.EXPECTED_SIZE} bytes but got: {filesize}"
                )
                sys.exit(2)
            print(f"Supported File Format Version: {RStats.ID_V1}")
            self.index = 0
            self.modified = modified
            self.data = StatsData(self.modified)
        except IOError:
            sys.stderr.write(f"Cannot read file: {filename}")
            traceback.print_exc()

    def dump(self):
        self._version_check()

        for entry_d in self._dump_stats(RStats.DAY_COUNT):
            self.data.add_daily(entry_d)
        print(f"daily counter: {self._unpack_value('q', 8)}")

        for entry_m in self._dump_stats(RStats.MONTH_COUNT):
            self.data.add_monthly(entry_m)
        print(f"monthly counter: {self._unpack_value('q', 8)}")

        self._completion_check()
        return self.data

    def print(self):
        self._version_check()

        print("---------- Daily ----------")
        self.print_stats(RStats.DAY_COUNT)
        print(f"dailyp: {self._unpack_value('q', 8)}")

        print("---------- Monthly ----------")
        self.print_stats(RStats.MONTH_COUNT)
        print(f"monthlyp: {self._unpack_value('q', 8)}")

        self._completion_check()

    def print_stats(self, size: int):
        print("Date (yyyy-mm-dd),Down (bytes),Up (bytes)")
        for stat in self._dump_stats(size):
            print(f"{stat[0].strftime(DATE_FORMAT)},{stat[1]},{stat[2]}")

    def _dump_stats(self, size: int):
        for _ in range(size):
            time = self._unpack_value("Q", 8)
            down = self._unpack_value("Q", 8)
            up = self._unpack_value("Q", 8)
            date = self.get_date(time)
            if date.year > 1900:
                yield (date, down, up)

    def _unpack_value(self, unpack_type: str, size: int):
        current = self.index
        self.index += size
        if self.index > RStats.EXPECTED_SIZE:
            sys.stderr.write(
                f"Reached end of the buffer. {self.index}/{RStats.EXPECTED_SIZE}"
            )
            sys.exit(3)
        (value,) = struct.unpack(unpack_type, self.file_content[current : self.index])
        return value

    def _version_check(self):
        """Check file format version"""
        version = self._unpack_value("Q", 8)
        print(f"Version: {version}")
        if version != RStats.ID_V1:
            sys.stderr.write(f"Unknown version number: {version}\n")
            sys.exit(2)

    def _completion_check(self):
        """Check if all bytes are read"""
        if self.index == self.EXPECTED_SIZE:
            print("All bytes read")
        else:
            print(">>> Warning!")
            print(f"Read {self.index} bytes.")
            print(f"Expected to read {RStats.EXPECTED_SIZE} bytes.")
            print(f"Left to read {RStats.EXPECTED_SIZE - self.index} bytes")

    @staticmethod
    def get_date(time):
        year = ((time >> 16) & 0xFF) + 1900
        month = ((time >> 8) & 0xFF) + 1
        day = time & 0xFF
        return datetime(year, month, 1 if day == 0 else day)
        # datetime will have hours and minutes set to 0


def compatibility(data):
    if "format" in data["meta"] and data["meta"]["format"] == LOG_FORMAT_VER:
        return data
    try:
        from util.update_log import data_update

        return data_update(data, LOG_FORMAT_VER)
    except ImportError as ie:
        raise ValueError("Log format outdated! Run updater.") from ie


def load_json_or_backup(path):
    try:
        with open(path, "r", encoding="utf8") as f:
            return json.loads(f.read())
    except json.JSONDecodeError as err:
        sys.stderr.write(f"JSON Decode Error at position {err.pos}: {err.msg}")
        copyfile(path, f"{path}.err")

    if isfile(f"{path}.bak"):
        try:
            with open(f"{path}.bak", "r", encoding="utf8") as f:
                return json.loads(f.read())
        except json.JSONDecodeError as err:
            sys.stderr.write(
                f"Error reading backup data: JSON Decode Error at position {err.pos}: {err.msg}"
            )
    else:
        sys.stderr.write("Unable to find backup file")

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", help="rstats history file")
    parser.add_argument("-o", "--out", help="output JSON file path")

    args = parser.parse_args()

    if isfile(args.filename):
        modified = get_time(file=args.filename)
        if args.out is None:
            RStats(args.filename, modified).print()
        else:
            stats = RStats(args.filename, modified).dump()
            if isfile(args.out):
                prev_export = load_json_or_backup(args.out)
                if prev_export is not None:
                    stats.merge_history(compatibility(prev_export))

            json_data = stats.to_json()
            with open(args.out, "w", encoding="utf8") as f:
                f.write(json_data)

            # Run backup once per day or if one doesn't exist yet
            do_backup = True
            backup_name = f"{args.filename}.bak"
            if isfile(backup_name):
                last_backup = get_time(file=backup_name)
                do_backup = last_backup.date() != NOW.date()
            if do_backup:
                copyfile(args.out, f"{args.out}.bak")
                copyfile(args.filename, backup_name)

    else:
        parser.exit(1, f"{args.filename} not found")


if __name__ == "__main__":
    main()
