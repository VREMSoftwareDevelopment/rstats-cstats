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

# IMPORTANT: Currently designed to run as a CRON job on the router every hour.
#            Script makes several assumptions based on this expectation.

import argparse
import gzip
import json
import math
import struct
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from os.path import isfile
from shutil import copyfile


SCRIPT_INTERVAL = timedelta(hours=1)


# Constants
PETABYTE = math.pow(1024, 5)
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


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
if NOW.tzinfo is not None and NOW.tzinfo.utcoffset(NOW) is not None:
    DATETIME_NAIVE = False
else:
    DATETIME_NAIVE = True


class Comment:  # pylint: disable=too-few-public-methods
    def __init__(
        self,
        message: str | None = None,
        cutoff_down: datetime | str | None = None,
        cutoff_up: datetime | str | None = None,
        daily: bool = False,
    ):
        if message is None:
            self.message = "Data error. Values are lower than actual."
        else:
            self.message = message
        self.cutoff_down = cutoff_down
        self.cutoff_up = cutoff_up
        self.is_daily = daily

    def export(self) -> dict[str, str | None]:
        if DATETIME_NAIVE or self.is_daily is False:
            return {"message": self.message}

        if self.cutoff_down is None:
            export_down = None
        else:
            export_down = (
                self.cutoff_down
                if isinstance(self.cutoff_down, str)
                else self.cutoff_down.strftime(TIME_FORMAT)
            )
        if self.cutoff_up is None:
            export_up = None
        else:
            export_up = (
                self.cutoff_up
                if isinstance(self.cutoff_up, str)
                else self.cutoff_up.strftime(TIME_FORMAT)
            )

        return {
            "message": self.message,
            "cutoff_down": export_down,
            "cutoff_up": export_up,
        }


class Props:  # pylint: disable=too-few-public-methods
    def __init__(
        self, date: datetime | str, down: int, up: int, comment: dict | None = None
    ):
        if isinstance(date, str):
            self.date = datetime.strptime(date, DATE_FORMAT)
        else:
            self.date = date
        self.down = down
        self.up = up
        # Comments only exist for previous data
        self.comment = comment


class DataPoint:
    # fmt: off
    _data_scale = {
        'kb': 1, 'kib': 1,
        'mb': 2, 'mib': 2,
        'gb': 3, 'gib': 3,
        'tb': 4, 'tib': 4,
        'pb': 5, 'pib': 5,
        'eb': 6, 'eib': 6
    }
    _data_scale_names = ('B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB')
    # fmt: on

    def __init__(self, props: Props, rollback_time: datetime, daily=False):
        self.rollback_time = rollback_time
        self.date = props.date  # WARNING: Naive datetime mainly for date and 00:00
        self.down = -1 if props.down > PETABYTE else props.down
        self.up = -1 if props.up > PETABYTE else props.up
        self.comment = props.comment
        if self.down == -1:
            self._warn_bad_data(daily, True)
        if self.up == -1:
            self._warn_bad_data(daily, False)

    def export(self):
        export_dict = {
            "date": self.date.strftime(DATE_FORMAT),
            "down": self.down,
            "up": self.up,
        }
        if self.comment is not None:
            export_dict["comment"] = self.comment
        return export_dict

    @staticmethod
    def format_bytes(size: int, scale: str = None) -> str:
        if size < 1024:
            return f"{size} B"

        scale = scale.lower()

        if scale is None or scale not in DataPoint._data_scale:
            exponent = int(math.floor(math.log(size, 1024)))
        else:
            exponent = DataPoint._data_scale[scale]

        divisor = math.pow(1024, exponent)
        value = round(size / divisor, 2)
        return f"{value} {DataPoint._data_scale_names[exponent]}"

    @property
    def date_string(self) -> str:
        return self.date.strftime(DATE_FORMAT)

    @property
    def total_bytes(self) -> int:
        return self.down + self.up

    def _warn_bad_data(
        self,
        is_daily: bool = False,
        is_down: bool = False,
        msg: str | None = None,
    ):
        """Make note of error and set last known good data time, if applicable.
        Only called when working on current data."""
        if self.comment is None:
            self.comment = Comment(message=msg, daily=is_daily)

        if is_daily and not DATETIME_NAIVE:
            if self.date.date() > self.rollback_time.date():
                # If it's a new day with no prior data, limit to current date
                self.rollback_time = self.date
            if is_down:
                self.comment.cutoff_down = self.rollback_time
            else:
                self.comment.cutoff_up = self.rollback_time
        else:
            # Monthly comments don't use timestamps
            self.comment.message = msg

    def __str__(self) -> str:
        return (
            f"{self.date.strftime(DATE_FORMAT)}: "
            + f"{DataPoint.format_bytes(self.down)}, "
            + f"{DataPoint.format_bytes(self.up)}"
        )


class StatsData:
    def __init__(self, modified: datetime) -> None:
        self.daily: dict = {}
        self.monthly: dict = {}
        self.modified_time = modified
        self.rollback_time = self.modified_time - SCRIPT_INTERVAL  # Estimate

    def export(self) -> dict:
        return {
            "meta": {
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
        except:
            raise TypeError(  # pylint: disable=raise-missing-from
                f"Unable to serialize {obj} of type {type(obj)}"
            )

    def add_daily(self, entry: tuple[datetime, int, int]):
        new_data = DataPoint(Props(*entry), self.rollback_time, daily=True)
        self.daily[new_data.date_string] = new_data

    def add_monthly(self, entry: tuple[datetime, int, int]):
        new_data = DataPoint(Props(*entry), self.rollback_time)
        self.monthly[new_data.date_string] = new_data

    def merge_history(self, previous_data):
        # Previous data uses normal dict
        if "meta" in previous_data:
            # Update estimate with actual value
            self.rollback_time = datetime.fromisoformat(
                previous_data["meta"]["time_data"]
            )

        if "daily" in previous_data:
            for previous in previous_data["daily"]:
                prev_date = previous["date"]
                if prev_date is None:
                    continue
                # Use old data to fill in history and roll back errors
                if prev_date in self.daily:
                    self._merge_history_logic(self.daily[prev_date], previous, True)
                else:
                    self.daily[prev_date] = DataPoint(
                        Props(**previous), self.rollback_time, True
                    )

        if "monthly" in previous_data:
            for previous in previous_data["monthly"]:
                prev_date = previous["date"]
                if prev_date is None:
                    continue
                # Use old data to fill in history and roll back errors
                if prev_date in self.monthly:
                    self._merge_history_logic(self.monthly[prev_date], previous, False)
                else:
                    self.monthly[prev_date] = DataPoint(
                        Props(**previous), self.rollback_time
                    )

    def _merge_history_logic(self, curr: DataPoint, prev: dict, is_daily: bool = False):
        # Set to highest value
        curr.down = max(curr.down, prev["down"])
        curr.up = max(curr.up, prev["up"])

        if "comment" in prev:
            prev_cmt = prev["comment"]
            if curr.comment is None:
                curr.comment = Comment(daily=is_daily)

            curr.comment.message = prev_cmt["message"]
            if "cutoff_down" in prev_cmt and prev_cmt["cutoff_down"] is not None:
                curr.comment.cutoff_down = prev_cmt["cutoff_down"]
                # Freeze to last known uncorrupted(?) data
                curr.down = prev["down"]
            if "cutoff_up" in prev_cmt and prev_cmt["cutoff_up"] is not None:
                curr.comment.cutoff_up = prev_cmt["cutoff_up"]
                curr.up = prev["up"]


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

            if len(self.file_content) != RStats.EXPECTED_SIZE:
                print(
                    "Unsupported File Format. Require unzip file size: "
                    + f"{RStats.EXPECTED_SIZE}."
                )
                sys.exit(2)
            print(f"Supported File Format Version: {RStats.ID_V1}")
            self.index = 0
            self.modified = modified
            self.data = StatsData(self.modified)
        except IOError:
            sys.stderr.write("Can NOT read file: " + filename)
            traceback.print_exc()

    def dump(self):
        self._version_check()

        for entry_d in self._dump_stats(RStats.DAY_COUNT):
            self.data.add_daily(entry_d)
        self._unpack_value("q", 8)

        for entry_m in self._dump_stats(RStats.MONTH_COUNT):
            self.data.add_monthly(entry_m)
        self._unpack_value("q", 8)

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    parser.add_argument("-o", "--out")

    args = parser.parse_args()

    if isfile(args.filename):
        modified = get_time(file=args.filename)
        if args.out is None:
            RStats(args.filename, modified).print()
        else:
            stats = RStats(args.filename, modified).dump()
            if isfile(args.out):
                try:
                    with open(args.out, "r", encoding="utf8") as f:
                        prev_export = json.loads(f.read())
                    stats.merge_history(prev_export)
                except json.JSONDecodeError as err:
                    sys.stderr.write("JSON Decode Error: " + err.msg)
                    copyfile(args.out, f"{args.out}.err")

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
