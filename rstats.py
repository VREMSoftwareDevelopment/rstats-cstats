#!/usr/bin/python
#
# reference rstats.c TomatoUsb source code
#
#
#    Copyright (C) 2010 - 2015 VREM Software Development <VREMSoftwareDevelopment@gmail.com>
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

from datetime import date
import traceback
import gzip
import struct
import sys


# rstats supports version ID_V1
class RStats(object):
    # expected file size in bytes
    EXPECTED_SIZE = 2112
    # version 0 has 12 entries per month
    ID_V0 = 0x30305352
    # version1 has 25 entries per month
    ID_V1 = 0x31305352

    MONTH_COUNT = 25
    DAY_COUNT = 62

    def __init__(self, filename):
        try:
            print(">>>>>>>>>> Tomato USB RSTATS <<<<<<<<<<")
            with gzip.open(filename, 'rb') as fileHandle:
                self.fileContent = fileHandle.read()
            if len(self.fileContent) != RStats.EXPECTED_SIZE:
                print("Unsupported File Format. Require unzip file size: {0}.".format(RStats.EXPECTED_SIZE))
                sys.exit(2)
            print("Supported File Format Version: {0}".format(RStats.ID_V1))
            self.index = 0
        except IOError:
            sys.stderr.write("Can NOT read file: "+filename)
            traceback.print_exc()

    def dump(self):
        version = self.unpack_value("Q", 8)
        print("Version: {0}".format(version))
        if version != RStats.ID_V1:
            sys.stderr.write("Unknown version number: {0}\n".format(version))
            sys.exit(2)

        print("---------- Daily ----------")
        self.dump_stats(RStats.DAY_COUNT)
        print("dailyp: {0}".format(self.unpack_value("q", 8)))

        print("---------- Monthly ----------")
        self.dump_stats(RStats.MONTH_COUNT)
        print("monthlyp: {0}".format(self.unpack_value("q", 8)))

        # check if all bytes are read
        if self.index == self.EXPECTED_SIZE:
            print("All bytes read")
        else:
            print(">>> Warning!")
            print("Read {0} bytes.".format(self.index))
            print("Expected to read {0} bytes.".format(RStats.EXPECTED_SIZE))
            print("Left to read {0} bytes".format(RStats.EXPECTED_SIZE - self.index))

    def dump_stats(self, size):
        print("Date (yyyy/mm/dd),Down (bytes),Up (bytes)")
        for i in range(size):
            time = self.unpack_value("Q", 8)
            down = self.unpack_value("Q", 8)
            up = self.unpack_value("Q", 8)
            print("{0},{1},{2}".format(self.get_date(time).strftime("%Y/%m/%d"), down, up))

    def unpack_value(self, unpack_type, size):
        current = self.index
        self.index += size
        if self.index > RStats.EXPECTED_SIZE:
            sys.stderr.write("Reached end of the buffer. {0}/{1}".format(self.index, RStats.EXPECTED_SIZE))
            exit(3)
        value, = struct.unpack(unpack_type, self.fileContent[current:self.index])
        return value

    @staticmethod
    def get_date(time):
        year = ((time >> 16) & 0xFF) + 1900
        month = ((time >> 8) & 0xFF) + 1
        day = time & 0xFF
        return date(year, month, 1 if day == 0 else day)


def main():
    import optparse
    from os.path import isfile

    usage = "usage: %prog <filename>"
    parser = optparse.OptionParser(usage)

    options, args = parser.parse_args()

    if len(args) == 1 and isfile(args[0]):
        RStats(args[0]).dump()
    else:
        print(usage)
        sys.exit(1)


if __name__ == "__main__":
    main()
