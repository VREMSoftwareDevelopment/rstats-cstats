import argparse
import json


CURRENT_VERSION = 2


def v1_upgrade(data: dict):
    """Convert file version 1"""
    for idx in range(len(data["daily"])):
        old_dict = data["daily"][idx]
        new_dict = {
            "date": old_dict["date"],
            "traffic": [old_dict["down"], old_dict["up"]],
            "error": [False, False],
        }
        if "comment" in old_dict:
            err_down = False if old_dict["comment"]["cutoff_down"] is None else True
            err_up = False if old_dict["comment"]["cutoff_up"] is None else True
            new_dict["error"] = [err_down, err_up]
            new_dict["misc"] = {
                "comment": old_dict["comment"]["message"],
                "cutoff_down": old_dict["comment"]["cutoff_down"],
                "cutoff_up": old_dict["comment"]["cutoff_up"],
            }
        data["daily"][idx] = new_dict
    for idx in range(len(data["monthly"])):
        old_dict = data["monthly"][idx]
        new_dict = {
            "date": old_dict["date"],
            "traffic": [old_dict["down"], old_dict["up"]],
            "error": ["comment" in old_dict, False],
        }
        if "comment" in old_dict:
            new_dict["misc"] = {"comment": old_dict["comment"]["message"]}
        data["monthly"][idx] = new_dict
    return data


def data_interop(data: dict, current_ver: int) -> dict:
    try:
        if "format" in data["meta"]:
            data_ver = data["meta"]["format"]
            if data_ver == current_ver:
                return data
            if data_ver == 1:
                return v1_upgrade(data)
            # Insert version numbers here
            if data_ver > current_ver:
                raise ValueError(
                    f"Data format version {data_ver} > script format version {current_ver}"
                )
            raise ValueError(f"{data_ver} is not a valid version number")
        # No format version info (version 1)
        return v1_upgrade(data)
    except Exception as err:  # pylint: disable=broad-exception-caught
        print("Exception occured during data interop processing:\n", err)
        return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="RStats-Logger Interop",
        description="Convert older JSON logs to newer format",
    )
    parser.add_argument("path", required=True)
    args = parser.parse_args()

    with open(args.path, "r", encoding="utf8") as f:
        file_data = json.loads(f.read())
    data_interop(file_data, CURRENT_VERSION)
    with open(args.path, "w", encoding="utf8") as f:
        f.write(json.dumps(file_data))
