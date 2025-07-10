#!/usr/bin/env python3
"""
Upload Memory Reports to MemBrowse

This script enriches memory analysis reports with metadata and uploads
them to the MemBrowse API using the requests library.
"""

import argparse
import json
import sys
import requests
from typing import Dict, Any


class MemBrowseUploader:
    """Handles uploading reports to MemBrowse API"""
    
    def __init__(self, api_key: str, api_endpoint: str):
        self.api_key = api_key
        self.api_endpoint = api_endpoint
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'MemBrowse-Action/1.0.0'
        })
    
    def upload_report(self, report_data: Dict[str, Any]) -> bool:
        """Upload report to MemBrowse API using requests"""
        try:
            print(f"Uploading report to MemBrowse: {self.api_endpoint}")
            
            # Make the POST request directly with the data
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
        except Exception as e:
            print(f"Upload error: {e}", file=sys.stderr)
            return False


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
    parser.add_argument('--print-report', action='store_true', help='Print report to stdout')
    args = parser.parse_args()
    
    try:
        # Create metadata
        metadata = {
            'commit_sha': args.commit_sha,
            'commit_message': args.commit_message,
            'base_sha': args.base_sha,
            'branch_name': args.branch_name,
            'repository': args.repository,
            'target_name': args.target_name,
            'timestamp': args.timestamp,
            'analysis_version': args.analysis_version
        }
        
        # Load base report and merge with metadata
        with open(args.base_report, 'r') as f:
            base_report = json.load(f)
        
        enriched_report = {
            'metadata': metadata,
            'memory_analysis': base_report
        }
        
        if args.print_report:
            print(json.dumps(enriched_report, indent=2))
        
        if args.api_key and args.api_endpoint:
            uploader = MemBrowseUploader(args.api_key, args.api_endpoint)
            success = uploader.upload_report(enriched_report)
            if not success:
                sys.exit(1)
        else:
            print("No API key provided, skipping upload", file=sys.stderr)
        
    except FileNotFoundError as e:
        print(f"Error: Base report file not found: {args.base_report}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in base report: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()