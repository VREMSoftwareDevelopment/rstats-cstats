def data_interop(data: dict, current_ver: int) -> str:
    try:
        if "format" in data["meta"] and data["meta"]["format"] == current_ver:
            return data
        if "format" not in data["meta"]:
            for idx in range(len(data["daily"])):
                if "comment" in data["daily"][idx]:
                    err_down = isinstance(
                        data["daily"][idx]["comment"].pop("cutoff_down", None), str
                    )
                    err_up = isinstance(
                        data["daily"][idx]["comment"].pop("cutoff_up", None), str
                    )
                    data["daily"][idx]["comment"]["error_down"] = err_down
                    data["daily"][idx]["comment"]["error_up"] = err_up
        return data
    except Exception as err:  # pylint: disable=broad-exception-caught
        print(err)
        return data
