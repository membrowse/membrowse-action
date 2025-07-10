#!/usr/bin/env python3
"""
Upload Memory Reports to MemBrowse

This script enriches memory analysis reports with metadata and uploads
them to the MemBrowse API using the requests library.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import requests
except ImportError:
    print("Error: requests library not found. Please install with: pip install requests", file=sys.stderr)
    sys.exit(1)


class ReportEnricher:
    """Enriches memory reports with metadata"""
    
    def __init__(self, base_report_path: str):
        self.base_report_path = Path(base_report_path)
        self._validate_input()
    
    def _validate_input(self) -> None:
        """Validate input files"""
        if not self.base_report_path.exists():
            raise FileNotFoundError(f"Base report not found: {self.base_report_path}")
        
        if not self.base_report_path.is_file():
            raise ValueError(f"Base report path is not a file: {self.base_report_path}")
    
    def enrich_report(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich the base report with metadata and return the enriched report"""
        try:
            # Read the base report
            with open(self.base_report_path, 'r') as f:
                base_report = json.load(f)
            
            # Create enriched report structure
            enriched_report = {
                'metadata': metadata,
                'memory_analysis': base_report
            }
            
            return enriched_report
            
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in base report: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to enrich report: {e}")


class MemBrowseUploader:
    """Handles uploading reports to MemBrowse API"""
    
    def __init__(self, api_key: str, api_endpoint: Optional[str] = None):
        self.api_key = api_key
        self.api_endpoint = api_endpoint or os.getenv(
            'MEMBROWSE_API_URL', 
            'https://api.membrowse.com/v1/reports'
        )
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'MemBrowse-Action/1.0.0'
        })
    
    def upload_report(self, report_path: Path) -> bool:
        """Upload report to MemBrowse API using requests"""
        if not report_path.exists():
            raise FileNotFoundError(f"Report file not found: {report_path}")
        
        try:
            print(f"Uploading report to MemBrowse: {self.api_endpoint}")
            
            # Read the report data
            with open(report_path, 'r') as f:
                report_data = json.load(f)
            
            # Make the POST request
            response = self.session.post(
                self.api_endpoint,
                json=report_data,
                timeout=30
            )
            
            # Check response
            if response.status_code == 200 or response.status_code == 201:
                print("Report uploaded successfully to MemBrowse")
                return True
            else:
                error_msg = f"HTTP {response.status_code}: {response.text}"
                print(f"Failed to upload report: {error_msg}", file=sys.stderr)
                return False
                
        except requests.exceptions.Timeout:
            print("Upload error: Request timed out", file=sys.stderr)
            return False
        except requests.exceptions.ConnectionError:
            print("Upload error: Failed to connect to MemBrowse API", file=sys.stderr)
            return False
        except requests.exceptions.RequestException as e:
            print(f"Upload error: {e}", file=sys.stderr)
            return False
        except json.JSONDecodeError as e:
            print(f"Upload error: Invalid JSON in report file: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"Upload error: {e}", file=sys.stderr)
            return False


def create_metadata(commit_sha: str, commit_message: str, base_sha: str,
                   branch_name: str, repository: str, target_name: str,
                   timestamp: str, analysis_version: str = "1.0.0") -> Dict[str, Any]:
    """Create metadata dictionary"""
    return {
        'commit_sha': commit_sha,
        'commit_message': commit_message,
        'base_sha': base_sha,
        'branch_name': branch_name,
        'repository': repository,
        'target_name': target_name,
        'timestamp': timestamp,
        'analysis_version': analysis_version
    }


def main() -> None:
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Enrich memory reports with metadata and optionally upload to MemBrowse',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --base-report report.json --commit-sha abc123 --target test --timestamp 2024-01-01T12:00:00Z
  %(prog)s --base-report report.json --api-key secret --commit-sha abc123 --target test --timestamp 2024-01-01T12:00:00Z
        """
    )
    
    # Required arguments
    parser.add_argument('--base-report', required=True, help='Path to base memory report JSON')
    parser.add_argument('--commit-sha', required=True, help='Git commit SHA')
    parser.add_argument('--commit-message', required=True, help='Git commit message')
    parser.add_argument('--target-name', required=True, help='Target platform name')
    parser.add_argument('--timestamp', required=True, help='Committer timestamp in ISO format')
    
    # Optional metadata
    parser.add_argument('--base-sha', default='', help='Base commit SHA for comparison')
    parser.add_argument('--branch-name', default='', help='Git branch name')
    parser.add_argument('--repository', default='', help='Repository name')
    parser.add_argument('--analysis-version', default='1.0.0', help='Analysis version')
    
    # Upload options
    parser.add_argument('--api-key', help='MemBrowse API key (uploads automatically if provided)')
    parser.add_argument('--api-endpoint', help='MemBrowse API endpoint URL')
    
    # Debug options
    parser.add_argument('--keep-temp', action='store_true', help='Keep temporary files')
    
    args = parser.parse_args()
    
    try:
        # Create metadata
        metadata = create_metadata(
            commit_sha=args.commit_sha,
            commit_message=args.commit_message,
            base_sha=args.base_sha,
            branch_name=args.branch_name,
            repository=args.repository,
            target_name=args.target_name,
            timestamp=args.timestamp,
            analysis_version=args.analysis_version
        )
        
        # Enrich the report
        enricher = ReportEnricher(args.base_report)
        enriched_report = enricher.enrich_report(metadata)
        
        # Upload if API key is provided
        if args.api_key:
            # Create a temporary file for upload
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                json.dump(enriched_report, temp_file, indent=2)
                temp_path = temp_file.name
            
            try:
                uploader = MemBrowseUploader(args.api_key, args.api_endpoint)
                success = uploader.upload_report(Path(temp_path))
                if not success:
                    sys.exit(1)
            finally:
                # Clean up temp file if not keeping
                if not args.keep_temp:
                    os.unlink(temp_path)
        else:
            print("No API key provided, skipping upload", file=sys.stderr)
        
        # Always print report to stdout
        print(json.dumps(enriched_report, indent=2))
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()