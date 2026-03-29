# Procapy

Programmer's Calculator in Python for Visual Studio Code. This is an inline calculator to use inside any document view in Visual Studio Code. Use inside existing views (e.g. source files) for quick inline calculations or dedicate a blank/unsaved view to use as an embedded standalone calculator.

## Usage

Simply select an expression (or multiple expressions using multiple selections) and execute the calculator by pressing the keyboard shortcut and the selection(s) will be replaced by the result of the calculation. Alternatively, if there are no selections, the line of the cursor will be parsed and the result inserted on the line after it (also works with multiple cursors). This is useful when using it as a normal calculator to incrementally perform a sequence of calculations using the result of the previous calculation as input for the following calculation leaving each step in the series of calculations visible.

Procapy supports any valid Python, and will reduce the result of any expression to a number (or an error string if something did not parse correctly).

The default keyboard shortcuts are:

 * Alt-Enter : Calculate and show conversions
 * Alt-~ : The key to the left of 1 - works even if the findWidget is open

## Built-in functions

In addition to the Python standard functions, math and cmath modules (the latter imported into the cmath namespace), Procapy adds the following functions that are useful in programming:

 * u(w, x): truncate x to an unsigned integer of width w.
 * u8(x), u16(x), u32(x), u64(x): truncate x to an unsigned integer of the indicated width.
 * i(w, x): truncate x to a signed integer of width w.
 * i8(x), i16(x), i32(x), i64(x): truncate x to a signed integer of the indicated width.

These are similar to the built-in function int(x) which will truncate to an integer of unlimited width.

In addition, the variable _n is assigned a value matching the index of each selection and the variable _m is assigned the total count of selections. This can be used in mathematical expressions to form different results for each selection.

## Examples

Difference between two hex numbers:

`0x0003 - 0x0007` → `-4`

Same but truncated to 32bit unsigned range which reveals the two's complement encoding of the negative number:

`u32(0x0003 - 0x0007)` → Hex: `0xfffffffc`

Division and addition:

`800 / 33 + 500 / 42` → Default: `36.14718614718615` → Simple: `36.15` → Scientific: `3.614719e+01`

Same but adding truncation to 8bit unsigned of intermediate results:

`u8(800 / 33) + u8(500 / 42)` → `35`

Interpretation of a positive hex number as unsigned integer:

`0xfffffffe` → `4294967294`

Same but showing truncatated to 32bit signed integer, revealing the value when interpreted as a two's complement encoding:

`i32(0xfffffffe)` → `-2`

Comparison operators return True/False in decimal mode and 0/1 in hex/binary/octal:

`0x0003 - 0xffff > 50` → Default: `False` → Hex: `0x0` → Binary: `0b0`

Mixed radix calculations:

 `0b1011 + 0x5 + 5` → Default: `21` → Hex: `0x15`

Bitwise operators (OR, NOT, AND, XOR):

 `0b1011 | ~0x5 & 5 ^ 0b101` → Default: `15` → Hex: `0xf` → Binary: `0b1111`

Shift operators:

 `(1 << 7) >> 3` → Default: `16` → Hex: `0x10` → Binary Group: `0b0001_0000`

Boolean operators and (in)equality:

 `45 > 5 and 6 < 7 or 5 == 3 and 4 != 4` → `True`

Rounding:

`round(4.51)` → `5`

Assignments (Ending expressions that are not None are assigned to _):

`x=5` followed by `x*5` → `25`

`2 + 6` followed by `_ * 2` → `16`

Addtional number suffixes:

`1/200µ` -> `5000.0`

`64KiB>>4` -> `4096`

`1PiB//1MiB` -> `1073741824`

C Style defines as assignments:
```c
CONFIG_NODES_SHIFT = 10
#define MAX_PHYSMEM_BITS	32
#define SECTION_SIZE_BITS	28
#define SECTIONS_SHIFT (MAX_PHYSMEM_BITS - SECTION_SIZE_BITS)
#define SECTIONS_WIDTH		SECTIONS_SHIFT
#define SECTIONS_PGOFF		((4*8) - SECTIONS_WIDTH)
#define SECTIONS_PGSHIFT	(SECTIONS_PGOFF * (SECTIONS_WIDTH != 0))
#define NODES_SHIFT CONFIG_NODES_SHIFT
#define NODES_WIDTH NODES_SHIFT
#define NODES_PGOFF		(SECTIONS_PGOFF - NODES_WIDTH)
#define NODES_PGSHIFT		(NODES_PGOFF * (NODES_WIDTH != 0))
NODES_PGSHIFT
```
→ `18`

C Style ints even when python styles strings:
```c
(20'000UL >> 13) * 'sample'
```
→ `samplesample`

Selections ending with = preserve the input (if you run calc on `6*7=`):

`Inside 6*7= a line` → `Inside 6*7=42 a line`

Figure out how long a 32 signed value with 1ms time can be before you wrap:

`2**31 * 1ms`

→ Default: `datetime.timedelta(seconds=2147, microseconds=483648)`

→ Simple: `0:35:47.483648`

→ Seconds: `2147.483648s`

Or how long it takes a 32bit 32.768kHz counter to wrap:

`u32(-1) * 1/32.768kHz`

→ Default: `datetime.timedelta(days=1, seconds=44671, microseconds=999969)`

→ Simple: `1 day, 12:24:31.999969`

→ Seconds: `131071.999969s`

## Configuration
There is a single config "Procapy: Startup Code" which can be changed in the settings.

Any globals in here is visible to scripts so it's a place where you can add your
own functions, or delete/change existing configs, or even provide additional types

The current default is:
```python
from math import *
import cmath
import datetime

def bs(v, idx):
    return bool(v & (1 << idx))
```

besides defining new functions you can also delete or override existing ones:
```python
uint32_t = u32
del u32
```

There are also special globals interact with the special numbers and alternatives
```python
import random
from math import pi
# Case sensitive mapping from suffix to a scalar multiplier
procapy_suffix_scales["pi"] = pi # Makes 2pi = 6.28

# Case insensive mapping from suffix to a function to replace with.
# The result is inserted into the source code as replacement 
# so be sure the str(result) is valid python code
procapy_suffix_handlers["rb"] = random.randbytes # Makes 4rb give 4 random bytes

# Modify the type handler map which is a 
# dict[type,dict[str, Optional[Callable[Any, Any]]]]
# The result if not None is passed through str and presented to the user.
procapy_type_handler_map[int]["log10"] = lambda x: log10(x) if x > 0 else None
del procapy_type_handler_map[int]["Oct"] # Remove octal as a conversion target
```

For the truely advanced it also possible to override these hooks to provide alternative behavior.
```python
def procapy_hook_display(value: Any) -> dict[str, Any]:
    """
    Provides a callback to gives any alternate form a value.
    Defaults to finding a key that is a values is a instanceof 
    in procapy_type_handler_map
    """

def procapy_hook_expandline(line: str, value: str) -> str:
    """
    Called to replace the line for zero width cursors
    Defaults to keeping the original line and adding the value after a newline
    """

def procapy_hook_extended_number(number: str, suffix: str):
    """
    Called for invalid numbers in the source code.
    Defaults to using procapy_suffix_scales and procapy_suffix_handlers 
    and replacing ' with _ before converting number.
    Should return a valid python expression that can be inserted into the source.
    """
```

## Acknowledgements

Icon designed by Freepik from Flaticon

## Release Notes

### 2.0.3
Breaking changes:
 * Use QuickPickItem to show different format options as the default key
 * Instead of using "n" add two variables instead _n and _m (selection count) available from the script
 * Rename i to _i to prevent issues with it accidently being redefined

Improvements:
 * Keep the python engine as singleton
 * Gives persistence to variables
 * Support for C style int literals
 * Support for some suffixes k,K,KiB,M,MiB,G,GiB,kB,MB,MiB,GB,GiB
 * Support for custom suffix handling
 * Support for C style #define as assignments
 * Support custom format options using a callback in python code
 * Support custom startup script to import/define custom functions and override hooks
 * Support for custom line replacement for empty selections
 * Add new int formats which use _ separator and align the number to a 2**2**n number (1,2,4,8,16,32,64,128bit etc.) in both hex and binary
 * Added an alternative keyboard shortcut that is not in conflict with the findWidget
 * If selection ends with = insert the result on the same line instead of the next

Minor Improvement/Bugs Fixes:
 * Correctly handle for n in range(10): ...
 * Fixed handling of escape chars in input string
 * Add package-lock file to make it clear what it have been tested against
 * Deleted unused testcases


### 1.1.1

 * Improve python path detection

### 1.1.0

 * Add support for multiple statements

### 1.0.0

 * Extend selection to full line when there is no selection

### 0.1.0

 * Acquire path to Python from the Python extension configuration
 * Move proca.py script to a location that is included in release package

### 0.0.3

 * Add icon by Freepik from Flaticon

### 0.0.2

 * Support hex/binary/octal
 * Add keybindings
 * Handle syntax errors from Python

### 0.0.1

Initial release of Procapy


