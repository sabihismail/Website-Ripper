import inspect
from typing import List

from src.util.generic import error


SAFE_PARAMETER_MAPPING = {
    'identifier': 'id'
}


def json_parse(json, key, default=None, fatal=False):
    if key in json:
        return json[key]

    if fatal:
        error(f'Cannot find {key} in {json}.')

    return default


def json_parse_enum(obj, json_val, class_type, fatal=False):
    val = json_parse(obj, json_val, default=None, fatal=fatal)

    if not val:
        return None

    val = str(val).upper()
    if val not in class_type.__dict__.keys():
        error(f'Invalid Enum: {val}, Keys: {class_type.__dict__.keys()}')

    return class_type.__dict__[val]


def json_parse_class(json, class_type, fatal: bool = False):
    args = inspect.getfullargspec(class_type.__init__).args
    args = [arg for arg in args if arg != 'self']

    d = {}
    for arg in args:
        if arg in SAFE_PARAMETER_MAPPING:
            temp_arg = SAFE_PARAMETER_MAPPING[arg]
        else:
            temp_arg = arg

        if temp_arg in json:
            d[arg] = json[temp_arg]

    obj = class_type(**d)

    return obj


def json_parse_class_list(json_array, class_type, fatal: bool = False):
    lst: List[class_type] = []

    for obj in json_array:
        obj: class_type = json_parse_class(obj, class_type, fatal=fatal)
        lst.append(obj)

    return lst
