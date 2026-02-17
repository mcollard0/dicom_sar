# DICOM Search/Replace & Dump Tool

High-performance, multithreaded command-line tool for processing DICOM files using Python 3.13t (Free-Threaded).

## Features

- **Dump Mode**: Inspect DICOM tag values with flexible filtering
- **Search and Replace Mode**: Modify DICOM tag values using regex patterns
- **Multithreading**: True parallelism leveraging Python 3.13t's no-GIL build
- **Safety**: Automatic backup mode (or optional in-place modification)
- **Validation**: VR constraint checking to prevent corruption
- **Progress Tracking**: Real-time progress bar and detailed reports

## Setup

### 1. Create Virtual Environment

```bash
python3.13t -m venv venv
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Dump Mode

Display DICOM tag values from files:

```bash
# Dump all tags from current directory
./dicom_sar.py --dump

# Dump from specific directory
./dicom_sar.py --dump --path /path/to/dicom/files

# Dump specific tag by keyword
./dicom_sar.py --dump --tag PatientID

# Dump specific tag by hex notation
./dicom_sar.py --dump --tag "(0010,0020)"

# Dump multiple tags
./dicom_sar.py --dump --tag "(0010,0020), (0010,0010)"
```

### Search and Replace Mode

Modify DICOM tag values using regex:

```bash
# Dry run (preview changes without writing)
./dicom_sar.py --sar \
  --regex_search '^(.*)$' \
  --regex_replace 'GENHOSP\1' \
  --tag PatientID \
  --dry-run

# Apply changes with automatic backup
./dicom_sar.py --sar \
  --regex_search '^(.*)$' \
  --regex_replace 'GENHOSP\1' \
  --tag "(0010,0020)"

# Apply changes in-place (no backup)
./dicom_sar.py --sar \
  --regex_search '^(.*)$' \
  --regex_replace 'GENHOSP\1' \
  --tag PatientID \
  --inplace

# Process all string-based VRs (requires --force)
./dicom_sar.py --sar \
  --regex_search 'OLD' \
  --regex_replace 'NEW' \
  --force
```

## Tag Format Support

The tool supports multiple tag input formats:

- **Keyword**: `PatientID`, `PatientName`
- **Hex notation**: `(0010,0020)`, `(0010, 0020)`
- **Lazy hex**: `10,20`, `(10,20)`
- **Multiple tags**: `"(0010,0020), (0010,0010)"`

## Command-Line Options

### Common Options

- `--path PATH`: Path to DICOM files (default: current directory)
- `--tag TAG`: Target tag(s) to process
- `--threads N`: Number of worker threads (default: CPU count - 4)
- `--verbose`: Enable verbose DEBUG logging

### Dump Mode

- `--dump`: Activate dump mode

### SAR Mode

- `--sar`: Activate search and replace mode
- `--regex_search PATTERN`: Regex pattern to find
- `--regex_replace PATTERN`: Replacement pattern (supports backreferences like `\1`)
- `--dry-run`: Preview changes without writing
- `--inplace`: Modify files in place (default: creates backups)
- `--force`: Allow SAR without --tag (processes all string VRs)

## Safety Features

### Backup Mode (Default)

By default, the tool operates in backup mode:
1. Original files are copied to `backup/` directory with timestamps
2. Modified files replace the originals
3. Backup filename format: `{filename}.{YYYYMMDD_HHMMSS}{ext}`

### VR Validation

The tool validates that modified values don't exceed DICOM VR (Value Representation) length limits:
- PN (Person Name): 64 characters
- LO (Long String): 64 characters
- SH (Short String): 16 characters
- etc.

### Error Handling

- Errors are logged to `logs/errors.log`
- Processing continues if individual files fail
- Final report shows error count

## Logging

- Main log: `logs/dicom_sar.log`
- Error log: `logs/errors.log`
- Console output: INFO level (DEBUG with `--verbose`)

## Performance

The tool uses Python 3.13t's free-threaded build for true parallel processing:
- Default workers: `max(1, CPU_count - 4)`
- Custom worker count: `--threads N`
- Progress tracking with `tqdm`

## Examples

### Example 1: Inspect Patient IDs

```bash
./dicom_sar.py --dump --tag PatientID --path ./dicom_files
```

### Example 2: Anonymize Patient IDs (with preview)

```bash
./dicom_sar.py --sar \
  --regex_search '^(.*)$' \
  --regex_replace 'ANON\1' \
  --tag PatientID \
  --dry-run \
  --path ./dicom_files
```

### Example 3: Add Prefix to Institution Name

```bash
./dicom_sar.py --sar \
  --regex_search '^(.*)$' \
  --regex_replace 'GENHOSP\1' \
  --tag InstitutionName \
  --path ./dicom_files
```

### Example 4: Replace Specific Value

```bash
./dicom_sar.py --sar \
  --regex_search 'OldHospital' \
  --regex_replace 'NewHospital' \
  --tag "(0008,0080)" \
  --path ./dicom_files
```

## Directory Structure

```
warp/
├── dicom_sar.py         # Main script
├── requirements.txt      # Python dependencies
├── README.md            # This file
├── venv/                # Virtual environment
├── backup/              # Backup files (auto-created)
├── logs/                # Log files (auto-created)
│   ├── dicom_sar.log
│   └── errors.log
└── tests/               # Test files
```

## Testing

See ARCHITECTURE.md for testing procedures.

## Notes

- Shell escaping: When using regex patterns with special characters like `$`, ensure proper escaping for your shell (e.g., use single quotes or escape the `$`)
- Some DICOM files may not have all tags; counts may not match total file counts
- The tool processes all files matching `*.*` pattern recursively
