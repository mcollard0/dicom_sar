# DICOM Search/Replace & Dump Tool Architecture

## Execution WARNING
- **ONLY YOUR OWN DIRECTORY!** Do not read any directories in .. except your own! Do not create and populate folders in any directory but your own. INCLUDING TESTS!
- **EAT THE FISH!** We're using fish shell. Stacking commands with || is not supported if the first command does not exist! Use type -q or command -v to check if a command exists before running it.

## Overview
A high-performance, multithreaded command-line tool `dicom_sar.py` for processing DICOM files using Python 3.13t (Free-Threaded). The tool supports searching/replacing DICOM tag values using regex and dumping DICOM headers with flexible filtering.

## Core Technology
- **Language**: Python 3.13t (Free-Threaded/No-GIL build)
- **Concurrency**: True parallelism using `concurrent.futures.ThreadPoolExecutor` (leveraging no-GIL)
- **DICOM Library**: `pydicom`
- **venv**: create `venv` in the same directory as the script using python 3.13t and install requirements

## Features & modes

### 1. Search and Replace (`--sar`)
Modification of DICOM tag values based on regex patterns.

- **Arguments**:
  - `--sar`: Activates search and replace mode.
  - `--regex_search`: Regex pattern to find (e.g., `^(.*)$`).
  - `--regex_replace`: Replacement pattern with backreferences (e.g., `GENHOSP\1`).
  - `--tag`: (Optional but Recommended) specific element to target, allowing "lazy" format (group,element) or keyword (e.g., `(10,20)`, `PatientID`). Use regex to parse multiples as example: "(0010, 0020), (0010,0010)". Spacing is variable. Input is HEX. Defaults to iterating all string-based VRs If omitted, require a --force flag. 
  - `--dry-run`: Preview changes without writing to disk.
  - `--inplace`: Modify files in place (default: False? Or default True with backup?). Setup: Safe by default (backup or new dir).

### 2. Dump (`--dump`)
Inspection of DICOM files.

- **Arguments**:
  - `--dump`: Activates dump mode.
  - `--tag`: Filter output to specific tags (supports lazy format like `10,10` for `0010,0010`).
  - `--recursive`: (Implied by default or explicit?)

### 3. File Discovery
- **Path**:
  - Default: Current directory (`.`)
  - `--path <dir>`: specific directory.
- **Mechanism**: Recursive glob (`rglob`) for `*.*` (as these dicom files are missing extension).

## Performance & Concurrency
- **Threading**:
  - Use `ThreadPoolExecutor` to manage worker threads.
  - **Worker Count**: Default to `max(1, os.cpu_count() - 4)` (leave some cores for system).
  - **Queue Management**: standard `queue.Queue` or executor map for backpressure, rather than manual sleep/waits.

## Observability & Logging
- **Logging**: Use `logging` module with INFO level for normal operation and DEBUG for verbose output to `dicom_sar.log`.
- **Metrics**:
  - Live progress bar (e.g., `tqdm`) or periodic status code updates.
  - Report:
    - Files processed count.
    - Files modified count.
    - Average processing time per file.
    - Total execution time.

## Safety & Validation
- **DICOM validation**: Ensure modifications don't corrupt VR constraints (e.g., length limits on SH/LO/PN).
- **Error Handling**: Log corrupt files or errors to a separate `errors.log` and continue processing.

## Testing
- Create a virtual environment with python 3.13t in the script folder 
- Install requirements to that venv
- Copy ALL DICOM files from /run/media/michael/FAST_ARCHIVE/DICOM/OFFIS/ to a test directory, ensuring permissions, write permission must exist when done, this has failed before.
- Run the tool against ALL FILES with --dump and --tag using example values above to verify the tool is working as expected -- it adds the string in the example.
- Verify with before and after sort/uniq/wc on the tag you are testing.
- Some files do not have a patient id and so the count is expected not to match. 

## Notes
# Manual Validation command: `find /run/media/michael/FAST_ARCHIVE/DICOM -type f -exec dcmdump +sd {} \; 2>/dev/null | grep "0010,0020" | sort | uniq -c | sort -rn`