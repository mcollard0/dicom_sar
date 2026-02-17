#!/usr/bin/env python3.13t
import argparse
import concurrent.futures
import logging
import os
import re
import sys
import time
from pathlib import Path
from queue import Queue

try:
    import pydicom
    from tqdm import tqdm
except ImportError:
    print("Error: pydicom and tqdm are required. Please install them using pip.")
    sys.exit(1)

# Configure logging
def setup_logging(verbose=False):
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('dicom_sar.log')
        ]
    )
    # Create a separate logger for errors
    error_logger = logging.getLogger('dicom_errors')
    error_logger.setLevel(logging.ERROR)
    error_handler = logging.FileHandler('errors.log')
    error_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    error_logger.addHandler(error_handler)
    return logging.getLogger(__name__), error_logger

def find_dicom_files(root_dir):
    """Recursively find all files in the directory using rglob."""
    # Architecture says: Recursive glob ('rglob') for *.* (as these dicom files are missing extension).
    # We will simply walk everything or use rglob("*").
    path = Path(root_dir)
    if not path.exists():
        return
    
    if path.is_file():
        yield str(path)
        return

    # Use rglob to find all files
    for p in path.rglob("*"):
        if p.is_file():
            yield str(p)

def parse_tag(tag_str):
    """Parse a DICOM tag string into a tuple (group, element) or keyword."""
    if not tag_str:
        return None
    
    # Remove parens and spaces for easier parsing of "10, 20" or "(0010, 0010)"
    clean_tag = tag_str.replace("(", "").replace(")", "").strip()
    
    # Check if it's a keyword (e.g., "PatientID")
    if re.match(r'^[a-zA-Z]+$', clean_tag):
        return clean_tag
    
    # Check for hex format (e.g., "0010,0010" or "10,20")
    # Splits by comma or space
    parts = re.split(r'[,\s]+', clean_tag)
    if len(parts) == 2:
        try:
            return (int(parts[0], 16), int(parts[1], 16))
        except ValueError:
            pass
            
    raise argparse.ArgumentTypeError(f"Invalid tag format: {tag_str}")

def dump_file(ds, tag_filter=None, logger=None):
    """Dump DICOM header information."""
    if tag_filter:
        try:
            # Handle both keyword and (group, element) tuple
            # Use data_element to get the DataElement object, not the value
            elem = ds.data_element(tag_filter)
            
            if elem:
                print(f"[{tag_filter}]: {elem.value}")
            else:
                pass # Silent if not found, or maybe log?
        except Exception:
            pass 
    else:
        print(ds)

def sar_file(ds, search_regex, replace_regex, tag_filter=None, logger=None):
    """Search and replace DICOM tag values."""
    modified = False
    try:
        regex = re.compile(search_regex)
    except re.error as e:
        if logger: logger.error(f"Invalid regex: {e}")
        return False

    def process_element(elem):
        nonlocal modified
        # Only process string-like VRs
        # Ensure elem is a DataElement and has VR
        if not hasattr(elem, 'VR'): 
            return

        if elem.VR in ('SH', 'LO', 'ST', 'LT', 'UT', 'PN', 'AE', 'CS', 'AS', 'DA', 'DT', 'TM', 'UI', 'UR'):
            try:
                val = elem.value
                if isinstance(val, str):
                    new_val = regex.sub(replace_regex, val)
                    if new_val != val:
                        elem.value = new_val
                        modified = True
                elif isinstance(val, list) or getattr(val, 'is_multival', False): # Multi-value
                    new_vals = []
                    changed = False
                    for v in val:
                        if isinstance(v, str):
                            nv = regex.sub(replace_regex, v)
                            if nv != v:
                                changed = True
                            new_vals.append(nv)
                        else:
                            new_vals.append(v)
                    if changed:
                        elem.value = new_vals
                        modified = True
            except Exception as e:
                # Some values might be bytes or have encoding issues
                pass

    if tag_filter:
         # Logic to handle specific tag targeting
        elem = ds.data_element(tag_filter)
        if elem:
            process_element(elem)
    else:
        # Iterate over all elements recursively? 
        # For now, let's iterate top level. If we need recursive (sequences), that's more complex.
        # Architecture doesn't explicitly mandate Sequence recursion but implied by "Search/Replace".
        # Let's stick to top-level for simplicity unless needed, or use ds.iterall()
        for elem in ds.iterall():
            process_element(elem)
            
    return modified

def process_single_file(file_path, args, logger, error_logger):
    """Process a single DICOM file based on arguments."""
    try:
        try:
            ds = pydicom.dcmread(file_path, force=True)
        except Exception as e:
            # Not a DICOM file or corrupt
            # error_logger.debug(f"Skipping {file_path}: {e}")
            return False, False

        if args.dump:
            print(f"--- {file_path} ---")
            dump_file(ds, args.tag, logger)
            return True, False

        if args.sar:
            if not args.regex_search:
                 logger.error("Regex search pattern required for SAR mode.")
                 return False, False
            
            modified = sar_file(ds, args.regex_search, args.regex_replace, args.tag, logger)
            
            if modified:
                if args.dry_run:
                    logger.info(f"[DRY-RUN] Would modify: {file_path}")
                    return True, False
                
                if args.inplace:
                    ds.save_as(file_path)
                    logger.info(f"Modified: {file_path}")
                    return True, True
                else:
                    logger.warning(f"File {file_path} modified but --inplace not set. Skipping save.")
                    return True, False
            
            return True, False

    except Exception as e:
        error_logger.error(f"Error processing {file_path}: {e}")
        return False, False

def main():
    parser = argparse.ArgumentParser(description="DICOM Search/Replace & Dump Tool")
    
    # Modes
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sar", action="store_true", help="Search and Replace mode")
    group.add_argument("--dump", action="store_true", help="Dump mode")
    
    # SAR arguments
    parser.add_argument("--regex_search", help="Regex pattern to find")
    parser.add_argument("--regex_replace", help="Replacement pattern")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--inplace", action="store_true", help="Modify files in place")
    
    # Shared arguments
    parser.add_argument("--tag", type=parse_tag, help="Specific DICOM tag (e.g., 'PatientID', '(0010,0020)', '10,20')")
    parser.add_argument("--path", default=".", help="Directory to search (default: current)")
    # Recursive is implied by architecture, but let's keep the flag logic simple (find_dicom_files always works recursively)
    
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    logger, error_logger = setup_logging(args.verbose)
    
    if args.sar and not args.regex_search:
        parser.error("--regex_search is required for --sar mode")
        
    start_discovery = time.time()
    files = list(find_dicom_files(args.path))
    discovery_time = time.time() - start_discovery
    logger.info(f"Found {len(files)} files in {args.path} (took {discovery_time:.2f}s)")
    
    if not files:
        logger.warning("No files found.")
        return

    # Using max workers formula from architecture
    max_workers = max(1, os.cpu_count() - 4)
    logger.info(f"Starting execution with {max_workers} workers")
    
    start_time = time.time()
    processed_count = 0
    modified_count = 0
    
    # Use ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {executor.submit(process_single_file, f, args, logger, error_logger): f for f in files}
        
        # Use tqdm for progress bar
        with tqdm(total=len(files), unit="file") as pbar:
            for future in concurrent.futures.as_completed(futures):
                try:
                    success, modified = future.result()
                    if success:
                        processed_count += 1
                    if modified:
                        modified_count += 1
                except Exception as e:
                    error_logger.error(f"Worker exception: {e}")
                finally:
                    pbar.update(1)
                    
    end_time = time.time()
    duration = end_time - start_time
    
    logger.info(f"Execution complete in {duration:.2f} seconds")
    logger.info(f"Files processed: {processed_count}")
    logger.info(f"Files modified: {modified_count}")
    logger.info(f"Average time per file: {duration/processed_count if processed_count else 0:.4f}s")

if __name__ == "__main__":
    main()
