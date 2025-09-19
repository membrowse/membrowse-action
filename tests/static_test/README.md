# Static Variable Source Mapping Test Cases

This directory contains test cases for verifying correct source file mapping of static variables in different scenarios.

## Test Cases

### 1. `header_static/` - Static Variables Defined in Headers

**Scenario**: Static variable defined in a header file and included by multiple compilation units.

**Files**:
- `c.h`: `static int foo = 42;` (definition in header)
- `a.c`: `#include "c.h"`, uses `foo`
- `b.c`: `#include "c.h"`, uses `foo`

**Expected Result**: Both `foo` symbols should be mapped to `"c.h"` since that's where the variable is actually defined.

### 2. `c_static/` - Separate Static Variables with Same Name

**Scenario**: Static variables with the same name defined in different source files.

**Files**:
- `a.c`: `static int foo = 0;` (first definition)
- `b.c`: `static int foo = 0;` (second definition)

**Expected Result**:
- First `foo` symbol should be mapped to `"a.c"`
- Second `foo` symbol should be mapped to `"b.c"`

### 3. `header_declaration_static/` - Header Declaration vs Source Definition

**Scenario**: Variable declared in header (`extern`) but defined in source file.

**Files**:
- `c.h`: `extern int foo;` (declaration only)
- `a.c`: `int foo = 0;` (actual definition)
- `b.c`: `#include "c.h"`, uses `foo`

**Expected Result**: The `foo` symbol should be mapped to `"a.c"` (where it's defined) not `"c.h"` (where it's only declared).

## Compilation

Each test case is compiled with:
```bash
gcc -g -o a.out *.c
```

The `-g` flag is essential for generating DWARF debug information needed for source file mapping.

## Testing

These test cases are automatically tested by `test_static_variable_source_mapping.py` which:

1. Compiles each test case using GCC with debug information
2. Generates memory reports using the MemBrowse CLI
3. Verifies that `foo` symbols are correctly mapped to their expected source files
4. Validates the overall report structure and symbol information

## Key Technical Points

- **DWARF Debug Information**: The source mapping relies on DWARF debug information in the compiled ELF files
- **Symbol Deduplication**: The system handles compiler-generated duplicate file entries in DWARF data
- **Declaration vs Definition**: Smart logic distinguishes between variable declarations and definitions
- **Static Variable Handling**: Special processing for static variables that may not have meaningful DWARF addresses