#!/usr/bin/python3
import ast
import json
import re
import tokenize
import traceback
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from itertools import accumulate
from math import log10
from pprint import pformat
from sys import stdin, stdout
from textwrap import dedent
from typing import Any, Callable, Dict, Optional, Union


# Truncation to arbitrary width unsigned integer
def _u(width: int, value: int) -> int:
    return int(value) & (2**width - 1)


def u8(value: int) -> int:
    return _u(8, value)


def u16(value: int) -> int:
    return _u(16, value)


def u32(value: int) -> int:
    return _u(32, value)


def u64(value: int) -> int:
    return _u(64, value)


# Truncation to arbitrary width signed integer
def _i(width: int, value: int) -> int:
    result = int(value) & (2 ** (width - 1) - 1)
    if int(value) & (1 << (width - 1)):
        result = -((result ^ (2 ** (width - 1) - 1)) + 1)
    return result


def i8(value: int) -> int:
    return _i(8, value)


def i16(value: int) -> int:
    return _i(16, value)


def i32(value: int) -> int:
    return _i(32, value)


def i64(value: int) -> int:
    return _i(64, value)


procapy_suffix_scales: Dict[str, Union[float, int]] = {
    "Q": 1000**10,
    "R": 1000**9,
    "Y": 1000**8,
    "Z": 1000**7,
    "E": 1000**6,
    "P": 1000**5,
    "T": 1000**4,
    "G": 1000**3,
    "M": 1000**2,
    "k": 1000,
    "h": 100,
    "da": 10,
    "d": 1e-1,
    "c": 1e-2,
    "m": 1e-3,
    "µ": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
    "a": 1e-18,
    "z": 1e-21,
    "y": 1e-24,
    "r": 1e-27,
    "q": 1e-30,
    "QiB": 1024**10,
    "RiB": 1024**9,
    "YiB": 1024**8,
    "ZiB": 1024**7,
    "EiB": 1024**6,
    "PiB": 1024**5,
    "TiB": 1024**4,
    "GiB": 1024**3,
    "MiB": 1024**2,
    "KiB": 1024,
    "kiB": 1024,
    "K": 1024,
}


class Frequency:
    hz: float

    def __init__(self, hz) -> None:
        self.hz = hz

    def __str__(self) -> str:
        if isinstance(self.hz, float):
            scale = log10(self.hz)
            if scale >= 6:
                return f"{self.hz/1e6}MHz"
            if scale >= 3:
                return f"{self.hz/1e3}kHz"
        return f"{self.hz}Hz"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(hz={self.hz})"

    def __truediv__(self, other) -> Union["Frequency", float]:
        if isinstance(other, Frequency):
            return self.hz / other.hz
        if isinstance(other, int) or isinstance(other, float):
            return Frequency(hz=self.hz / other)
        return NotImplemented

    def __rtruediv__(self, other) -> timedelta:
        if isinstance(other, int) or isinstance(other, float):
            return timedelta(seconds=other / self.hz)
        return NotImplemented

    def __mul__(self, other) -> Union["Frequency", float]:
        if isinstance(other, int) or isinstance(other, float):
            return Frequency(hz=self.hz * other)
        if isinstance(other, timedelta):
            return other.total_seconds() * self.hz
        return NotImplemented

    def __rmul__(self, other) -> Union["Frequency", float]:
        return self.__mul__(other)


procapy_suffix_handlers: Dict[str, Callable[[Any], Any]] = {
    "l": i32,
    "u": u32,
    "ul": u32,
    "uz": u32,
    "ll": i64,
    "ull": u64,
    "hz": lambda x: Frequency(x),
    "khz": lambda x: Frequency(1000 * x),
    "mhz": lambda x: Frequency(1000000 * x),
    "ms": lambda x: timedelta(microseconds=x),
    "µs": lambda x: timedelta(microseconds=x),
    "s": lambda x: timedelta(seconds=x),
    "sec": lambda x: timedelta(seconds=x),
    "second": lambda x: timedelta(seconds=x),
    "seconds": lambda x: timedelta(seconds=x),
    "min": lambda x: timedelta(minutes=x),
    "minute": lambda x: timedelta(minutes=x),
    "minutes": lambda x: timedelta(minutes=x),
    "hour": lambda x: timedelta(hours=x),
    "hours": lambda x: timedelta(hours=x),
}


def procapy_hook_extended_number(number: str, suffix: str) -> str:
    parsed_number: Union[float, int] = ast.literal_eval(number.replace("'", "_"))
    if suffix in procapy_suffix_scales:
        return repr(parsed_number * procapy_suffix_scales[suffix])
    handler = procapy_suffix_handlers.get(suffix.lower())
    if handler:
        return repr(handler(parsed_number))
    raise SyntaxError(f"Invalid suffix: {suffix}")


def procapy_bin_display(value: int) -> str:
    mag = (value).bit_length()
    width = 2 ** ((mag - 1).bit_length())
    return f"{value:#0{width+1+width//4 + (value<0)}_b}"


def procapy_hex_display(value: int) -> str:
    mag = (value).bit_length()
    width = 2 ** ((mag - 1).bit_length()) // 4
    return f"{value:#0{width+1+width//4 + (value<0)}_x}"


seq_map: Dict[str, Callable[[Any], str]] = {
    "Default": str,
    "Pretty": lambda x: pformat(x, compact=True, underscore_numbers=True),
}

procapy_type_handler_map: Dict[type, Dict[str, Callable[[Any], str]]] = defaultdict(dict,{
    timedelta: {
        "Default": repr,
        "Simple": str,
        "Seconds": lambda x: str(x.total_seconds()) + "s",
    },
    datetime: {
        "Default": repr,
        "Simple": str,
        "ISO": lambda x: x.isoformat(),
    },
    int: {
        "Default": str,
        "Decimal Group": lambda x: f"{x:_d}",
        "Hex Group": procapy_hex_display,
        "Hex": hex,
        "Binary Group": procapy_bin_display,
        "Binary": bin,
        "Oct": oct,
    },
    float: {
        "Default": str,
        "Simple": lambda x: f"{x:.2f}",
        "Scientific": lambda x: f"{x:e}",
    },
    bytes: {
        "Default": repr,
        "Byte Hex": lambda x: x.hex(),
        "Byte Hex Space": lambda x: x.hex(" "),
        "C Array": lambda x: "0x" + x.hex(" ").replace(" ", ", 0x"),
    },
    dict: seq_map,
    tuple: seq_map,
    list: seq_map,
    set: seq_map,
})


def procapy_hook_display(value: Any) -> Optional[dict[str, Callable[[Any], str]]]:
    for k, v in procapy_type_handler_map.items():
        if isinstance(value, k):
            return v


def procapy_hook_expandline(line: str, value: str) -> str:
    return f"{line}\n{value}"


variables: Dict[str, Any] = {
    "procapy_suffix_scales": procapy_suffix_scales,
    "procapy_suffix_handlers": procapy_suffix_handlers,
    "procapy_type_handler_map": procapy_type_handler_map,
    "procapy_hook_display": procapy_hook_display,
    "procapy_hook_expandline": procapy_hook_expandline,
    "procapy_hook_extended_number": procapy_hook_extended_number,
    "Frequency": Frequency,
    "_u": _u,
    "u": _u,
    "u8": u8,
    "u16": u16,
    "u32": u32,
    "u64": u64,
    "_i": _i,
    "i": _i,
    "i8": i8,
    "i16": i16,
    "i32": i32,
    "i64": i64,
}


def replace_outside_strings(pattern: re.Pattern[str], repl: Callable[[re.Match], str], source: str):
    # Collect the ranges of all string tokens
    string_ranges = []
    tokens = tokenize.generate_tokens(
        StringIO(re.sub(r"(?<=\d)'(?=\d)", "_", source)).readline
    )
    lines = source.splitlines(keepends=True)
    line_offsets = list(accumulate((len(line) for line in lines), initial=0))
    for tok_type, _, start, end, _ in tokens:
        if tok_type == tokenize.STRING:
            string_ranges.append(
                (
                    line_offsets[start[0] - 1] + start[1],
                    line_offsets[end[0] - 1] + end[1],
                )
            )

    def safe_sub(m: re.Match) -> str:
        # Suppress the substitution if the match falls inside a string literal
        pos = m.start()
        if any(s <= pos < e for s, e in string_ranges):
            return m.group(0)
        return repl(m)

    return pattern.sub(safe_sub, source)


extended_number_literals = re.compile(
    r"""
        (
            (?:-|\b) #Start of number
            (?:
                0x[0-9a-f]+(?:[_'][0-9a-f]+)*(?![a-f]) #Hex Number
                | 0b[01]+(?:[_'][01]+)* #Binary Number
                | 0o[0-7]+(?:[_'][0-7]+)* #Octal Number
                | [1-9][0-9]*(?:[_'][0-9]+)* #Decimal Number
                | [0-9]+(?:[_'][0-9]+)*\.(?:[0-9]+(?:[_'][0-9]+)*)?(?:e[+-]?[0-9]+(?:[_'][0-9]+)*)? #Float Number
                | 0(?![xbo])
            )
        )
        (?![je]) # Do not match complex numbers
        ([^\W\d_]+) #Suffix
    """,
    re.IGNORECASE | re.VERBOSE,
)

define_setter = re.compile(r"^#\s*define\s+(\w+)[^\S\r\n]+(\S.*)$", re.MULTILINE)


def handle_block(block: str) -> Any:
    program = dedent(block)
    program = define_setter.sub(r"\1 = \2", program)
    try:
        code_block = ast.parse(program)
    except SyntaxError:
        program = replace_outside_strings(
            extended_number_literals,
            lambda m: str(variables["procapy_hook_extended_number"](*m.groups())),
            program,
        )
        code_block = ast.parse(program)

    ends_with_expression = code_block.body and isinstance(code_block.body[-1], ast.Expr)
    if ends_with_expression:
        expression = ast.Expression(code_block.body.pop().value)  # type: ignore
        exec(compile(code_block, filename="<procapy>", mode="exec"), variables)

        result = eval(compile(expression, filename="<procapy>", mode="eval"), variables)

        if result is not None:
            variables["_"] = result
        return result
    else:
        exec(program, variables)


while True:
    command, *args, size = stdin.buffer.readline().decode().strip().split(" ")
    try:
        size = int(size)
        block = stdin.buffer.read(size + 1).decode()  # Terminated with a newline
        if command == "EVAL":
            out = StringIO()
            variables["_n"] = int(args[0])
            variables["_m"] = int(args[1])
            selection = " ".join(args[2:])
            with redirect_stdout(out), redirect_stderr(out):
                expression_result = handle_block(block)
            print_result = out.getvalue()

            if print_result:
                if expression_result is None:
                    result = print_result
                    result_type = "RES"
                else:
                    result = print_result + str(expression_result)
                    result_type = "RES"
            else:
                if expression_result is None:
                    result = ""
                    result_type = "NOP"
                else:
                    conversion = variables["procapy_hook_display"](expression_result)
                    if conversion and selection in conversion:
                        result = conversion[selection](expression_result)
                        result_type = "RES"
                    elif conversion:
                        alt = {}
                        for k, handler in conversion.items():
                            if not handler:
                                continue
                            v = handler(expression_result)
                            if v is None:
                                continue
                            alt[k] = str(v)
                        result = json.dumps(alt)
                        result_type = "ALT"
                    else:
                        result = str(expression_result)
                        result_type = "RES"
        elif command == "SET":
            result = ""
            vars = json.loads(block)
            variables.update(**vars)
            result_type = "NOP"
        else:
            result = "Unknown Request"
            result_type = "ERR"
    except Exception as exc:
        result = "\n".join(traceback.format_exception(exc))
        result_type = "ERR"
    result = result.encode()
    stdout.buffer.write(f"{result_type} {len(result)}\n".encode())
    stdout.buffer.write(result)
    stdout.buffer.write(b"\n")
    stdout.buffer.flush()
