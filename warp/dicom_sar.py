#!/usr/bin/env python3
"""
DICOM Search and Replace & Dump Tool
High-performance, multithreaded DICOM file processor using Python 3.13t (Free-Threaded)
"""

import argparse;
import logging;
import os;
import re;
import shutil;
import sys;
import time;
from concurrent.futures import ThreadPoolExecutor, as_completed;
from datetime import datetime;
from pathlib import Path;
from typing import List, Optional, Tuple, Dict, Set;

try:
    import pydicom;
    from pydicom.dataelem import DataElement;
    from pydicom.tag import Tag;
    from tqdm import tqdm;
except ImportError as e:
    print( f"Error: Missing required dependency: {e}" );
    print( "Please install requirements: pip install -r requirements.txt" );
    sys.exit( 1 );


# VR (Value Representation) length limits for validation
VR_MAX_LENGTHS = {
    'AE': 16,
    'AS': 4,
    'CS': 16,
    'DA': 8,
    'DS': 16,
    'DT': 26,
    'IS': 12,
    'LO': 64,
    'LT': 10240,
    'PN': 64,
    'SH': 16,
    'ST': 1024,
    'TM': 16,
    'UI': 64,
    'UT': 4294967294,
};


class DicomSARProcessor:
    """Main processor for DICOM search/replace and dump operations"""
    
    def __init__( self, args ):
        self.args = args;
        self.processed_count = 0;
        self.modified_count = 0;
        self.error_count = 0;
        self.start_time = None;
        self.processing_times = [];
        
        # Setup logging
        self._setup_logging();
        
        # Parse tags
        self.target_tags = self._parse_tags( args.tag ) if args.tag else None;
        
        # Determine worker count
        self.worker_count = args.threads if args.threads else max( 1, os.cpu_count() - 4 );
        self.logger.info( f"Using {self.worker_count} worker threads" );
    
    def _setup_logging( self ):
        """Configure logging to file and console"""
        log_dir = Path( __file__ ).parent / "logs";
        log_dir.mkdir( exist_ok=True );
        
        # Main log file
        log_file = log_dir / "dicom_sar.log";
        error_log_file = log_dir / "errors.log";
        
        # Configure root logger
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler( log_file ),
                logging.StreamHandler( sys.stdout )
            ]
        );
        
        self.logger = logging.getLogger( __name__ );
        self.logger.setLevel( logging.INFO if not self.args.verbose else logging.DEBUG );
        
        # Error logger
        self.error_logger = logging.getLogger( 'errors' );
        error_handler = logging.FileHandler( error_log_file );
        error_handler.setLevel( logging.ERROR );
        self.error_logger.addHandler( error_handler );
    
    def _parse_tags( self, tag_input: str ) -> List[Tag]:
        """Parse tag input supporting multiple formats: (0010,0020), 0010,0020, PatientID"""
        tags = [];
        
        # Pattern to match tags in various formats
        # Matches: (0010,0020), (0010, 0020), 0010,0020, 10,20, etc.
        pattern = r'\(?\s*([0-9a-fA-F]+)\s*,\s*([0-9a-fA-F]+)\s*\)?';
        matches = re.findall( pattern, tag_input );
        
        for group, element in matches:
            try:
                # Pad to 4 digits if needed (lazy format support)
                group_hex = group.zfill( 4 );
                element_hex = element.zfill( 4 );
                tag = Tag( int( group_hex, 16 ), int( element_hex, 16 ) );
                tags.append( tag );
                self.logger.debug( f"Parsed tag: {tag}" );
            except ValueError as e:
                self.logger.warning( f"Failed to parse tag ({group},{element}): {e}" );
        
        # Also try to parse as keyword
        if not matches:
            # Split by comma and try each as keyword
            keywords = [ kw.strip() for kw in tag_input.split( ',' ) ];
            for keyword in keywords:
                try:
                    tag = pydicom.datadict.tag_for_keyword( keyword );
                    if tag:
                        tags.append( Tag( tag ) );
                        self.logger.debug( f"Parsed keyword '{keyword}' as tag: {Tag( tag )}" );
                except Exception as e:
                    self.logger.warning( f"Failed to parse keyword '{keyword}': {e}" );
        
        return tags;
    
    def _discover_files( self, path: Path ) -> List[Path]:
        """Recursively discover all files in the given path"""
        self.logger.info( f"Discovering files in: {path}" );
        files = list( path.rglob( '*.*' ) );
        self.logger.info( f"Found {len( files )} files" );
        return files;
    
    def _validate_vr_length( self, value: str, vr: str ) -> bool:
        """Validate that the value doesn't exceed VR length constraints"""
        if vr in VR_MAX_LENGTHS:
            max_len = VR_MAX_LENGTHS[vr];
            if len( value ) > max_len:
                return False;
        return True;
    
    def _process_dump( self, file_path: Path ) -> Optional[Dict]:
        """Process a file in dump mode"""
        try:
            ds = pydicom.dcmread( str( file_path ), force=True );
            
            results = {};
            
            if self.target_tags:
                # Dump only specified tags
                for tag in self.target_tags:
                    if tag in ds:
                        elem = ds[tag];
                        results[tag] = {
                            'tag': str( tag ),
                            'keyword': elem.keyword,
                            'vr': elem.VR,
                            'value': str( elem.value )
                        };
            else:
                # Dump all tags
                for elem in ds:
                    if hasattr( elem, 'tag' ):
                        results[elem.tag] = {
                            'tag': str( elem.tag ),
                            'keyword': elem.keyword,
                            'vr': elem.VR,
                            'value': str( elem.value )
                        };
            
            return { 'file': str( file_path ), 'tags': results };
        
        except Exception as e:
            self.logger.error( f"Error dumping {file_path}: {e}" );
            self.error_logger.error( f"{file_path}: {e}" );
            self.error_count += 1;
            return None;
    
    def _process_sar( self, file_path: Path ) -> Optional[Dict]:
        """Process a file in search and replace mode"""
        file_start = time.time();
        modified = False;
        changes = [];
        
        try:
            ds = pydicom.dcmread( str( file_path ), force=True );
            
            # Determine which elements to process
            elements_to_process = [];
            
            if self.target_tags:
                # Process only specified tags
                for tag in self.target_tags:
                    if tag in ds:
                        elements_to_process.append( ds[tag] );
            else:
                # Process all string-based VRs
                string_vrs = { 'AE', 'AS', 'CS', 'DA', 'DS', 'DT', 'IS', 'LO', 'LT', 'PN', 'SH', 'ST', 'TM', 'UI' };
                for elem in ds:
                    if hasattr( elem, 'VR' ) and elem.VR in string_vrs:
                        elements_to_process.append( elem );
            
            # Apply regex search and replace
            for elem in elements_to_process:
                try:
                    old_value = str( elem.value );
                    new_value = re.sub( self.args.regex_search, self.args.regex_replace, old_value );
                    
                    if new_value != old_value:
                        # Validate VR length constraints
                        if not self._validate_vr_length( new_value, elem.VR ):
                            self.logger.warning(
                                f"Skipping {file_path} tag {elem.tag}: new value exceeds VR {elem.VR} max length"
                            );
                            continue;
                        
                        if not self.args.dry_run:
                            elem.value = new_value;
                        
                        modified = True;
                        changes.append( {
                            'tag': str( elem.tag ),
                            'keyword': elem.keyword,
                            'old': old_value,
                            'new': new_value
                        } );
                
                except Exception as e:
                    self.logger.warning( f"Error processing element {elem.tag} in {file_path}: {e}" );
            
            # Save the file if modified
            if modified and not self.args.dry_run:
                if self.args.inplace:
                    # Save in place
                    ds.save_as( str( file_path ) );
                else:
                    # Save to backup directory with timestamp
                    backup_dir = Path( __file__ ).parent / "backup";
                    backup_dir.mkdir( exist_ok=True );
                    
                    timestamp = datetime.now().strftime( '%Y%m%d_%H%M%S' );
                    backup_file = backup_dir / f"{file_path.stem}.{timestamp}{file_path.suffix}";
                    
                    # Copy original to backup
                    shutil.copy2( file_path, backup_file );
                    
                    # Save modified version
                    ds.save_as( str( file_path ) );
                
                self.modified_count += 1;
            
            self.processed_count += 1;
            processing_time = time.time() - file_start;
            self.processing_times.append( processing_time );
            
            return {
                'file': str( file_path ),
                'modified': modified,
                'changes': changes
            };
        
        except Exception as e:
            self.logger.error( f"Error processing {file_path}: {e}" );
            self.error_logger.error( f"{file_path}: {e}" );
            self.error_count += 1;
            return None;
    
    def run( self ):
        """Main execution method"""
        self.start_time = time.time();
        
        # Validate arguments
        if self.args.sar:
            if not self.args.regex_search or not self.args.regex_replace:
                self.logger.error( "SAR mode requires --regex_search and --regex_replace" );
                sys.exit( 1 );
            
            if not self.target_tags and not self.args.force:
                self.logger.error( "SAR mode without --tag requires --force flag" );
                sys.exit( 1 );
        
        # Discover files
        path = Path( self.args.path ) if self.args.path else Path( '.' );
        if not path.exists():
            self.logger.error( f"Path does not exist: {path}" );
            sys.exit( 1 );
        
        files = self._discover_files( path );
        
        if not files:
            self.logger.warning( "No files found to process" );
            return;
        
        # Process files
        self.logger.info( f"Processing {len( files )} files with {self.worker_count} workers" );
        
        results = [];
        
        with ThreadPoolExecutor( max_workers=self.worker_count ) as executor:
            # Submit all tasks
            if self.args.dump:
                futures = { executor.submit( self._process_dump, f ): f for f in files };
            else:  # SAR mode
                futures = { executor.submit( self._process_sar, f ): f for f in files };
            
            # Process with progress bar
            with tqdm( total=len( files ), desc="Processing files", unit="file" ) as pbar:
                for future in as_completed( futures ):
                    result = future.result();
                    if result:
                        results.append( result );
                        
                        # Print dump results
                        if self.args.dump and result.get( 'tags' ):
                            print( f"\n{result['file']}:" );
                            for tag_data in result['tags'].values():
                                print( f"  {tag_data['tag']} {tag_data['keyword']} [{tag_data['vr']}]: {tag_data['value']}" );
                        
                        # Print SAR changes
                        elif self.args.sar and result.get( 'modified' ):
                            if self.args.dry_run:
                                print( f"\n[DRY RUN] {result['file']}:" );
                            else:
                                print( f"\n{result['file']}:" );
                            
                            for change in result.get( 'changes', [] ):
                                print( f"  {change['tag']} {change['keyword']}: '{change['old']}' -> '{change['new']}'" );
                    
                    pbar.update( 1 );
        
        # Print final report
        self._print_report();
    
    def _print_report( self ):
        """Print final execution report"""
        total_time = time.time() - self.start_time;
        avg_time = sum( self.processing_times ) / len( self.processing_times ) if self.processing_times else 0;
        
        print( "\n" + "=" * 60 );
        print( "EXECUTION REPORT" );
        print( "=" * 60 );
        print( f"Files processed: {self.processed_count}" );
        
        if self.args.sar:
            print( f"Files modified: {self.modified_count}" );
            if self.args.dry_run:
                print( "[DRY RUN MODE - No changes written]" );
        
        print( f"Errors: {self.error_count}" );
        print( f"Average processing time: {avg_time:.4f}s per file" );
        print( f"Total execution time: {total_time:.2f}s" );
        print( "=" * 60 );


def main():
    parser = argparse.ArgumentParser(
        description="DICOM Search/Replace & Dump Tool - High-performance multithreaded processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dump all tags from DICOM files
  %(prog)s --dump --path /path/to/dicom/files

  # Dump specific tag
  %(prog)s --dump --tag PatientID

  # Search and replace (dry run)
  %(prog)s --sar --regex_search '^(.*)$' --regex_replace 'GENHOSP\\1' --tag PatientID --dry-run

  # Search and replace (in place)
  %(prog)s --sar --regex_search '^(.*)$' --regex_replace 'GENHOSP\\1' --tag '(0010,0020)' --inplace
        """
    );
    
    # Mode selection
    mode_group = parser.add_mutually_exclusive_group( required=True );
    mode_group.add_argument( '--dump', action='store_true', help='Dump mode: display DICOM tag values' );
    mode_group.add_argument( '--sar', action='store_true', help='Search and replace mode' );
    
    # Common arguments
    parser.add_argument( '--path', type=str, help='Path to DICOM files (default: current directory)' );
    parser.add_argument( '--tag', type=str, help='Target tag(s): (0010,0020), 10,20, or PatientID. Multiple tags: "(0010,0020), (0010,0010)"' );
    parser.add_argument( '--threads', type=int, help=f'Number of worker threads (default: cpu_count - 4)' );
    parser.add_argument( '--verbose', action='store_true', help='Enable verbose DEBUG logging' );
    
    # SAR-specific arguments
    parser.add_argument( '--regex_search', type=str, help='Regex pattern to search for (SAR mode)' );
    parser.add_argument( '--regex_replace', type=str, help='Replacement pattern with backreferences (SAR mode)' );
    parser.add_argument( '--dry-run', action='store_true', help='Preview changes without writing (SAR mode)' );
    parser.add_argument( '--inplace', action='store_true', help='Modify files in place (default: backup mode) (SAR mode)' );
    parser.add_argument( '--force', action='store_true', help='Allow SAR without --tag (processes all string VRs)' );
    
    args = parser.parse_args();
    
    # Create and run processor
    processor = DicomSARProcessor( args );
    processor.run();


if __name__ == '__main__':
    main();
