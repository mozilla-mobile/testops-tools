import json
import re
import sys
from datetime import datetime
from bs4 import BeautifulSoup

def parse_xcuitest_html(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        soup = BeautifulSoup(file, 'html.parser')
    
    test_suites = []
    
    suite_groups = soup.find_all("div", class_=re.compile(r"test-summary-group"))
    for suite in suite_groups:
        suite_name_tag = suite.find("p")
        if suite_name_tag:
            suite_text = suite_name_tag.get_text(strip=True)
            match = re.search(r"(.+)\((\d+\.\d+)s\)", suite_text)
            if match:
                suite_name = match.group(1).strip()
                suite_time = float(match.group(2))
                
                if suite_name in ["Selected tests", "XCUITests.xctest"]:
                    continue
                
                test_cases = []
                
                case_groups = suite.find_all("div", class_=re.compile(r"test-summary "))
                for case in case_groups:
                    case_name_tag = case.find("p", class_="list-item")
                    if case_name_tag:
                        case_text = case_name_tag.get_text(strip=True)
                        match = re.search(r"(.+)\((\d+\.\d+)s\)", case_text)
                        if match:
                            case_name = match.group(1).strip()
                            case_time = float(match.group(2))
                            
                            result = "failed" if "failed" in case.get("class", []) else "succeeded"
                            
                            test_cases.append({
                                "name": case_name,
                                "execution_time": case_time,
                                "result": result
                            })
                
                test_suites.append({
                    "name": suite_name,
                    "execution_time": suite_time,
                    "test_cases": test_cases
                })
    
    return test_suites

def extract_metadata_from_filename(filename):
    match = re.match(r"ios_insights_(?P<branch>[^_]+_[^_]+)_(?P<suite>[^_]+-[^_]+-[^_]+)-(?P<device>[^_]+)_(?P<timestamp>\d{8}-\d{6})\.html", filename)
    if match:
        return {
            "branch": match.group("branch"),
            "suite": match.group("suite"),
            "device": match.group("device"),
            "timestamp": datetime.strptime(match.group("timestamp"), "%Y%m%d-%H%M%S").isoformat()
        }
    return {}

def convert_to_ndjson(html_file, output_ndjson):
    metadata = extract_metadata_from_filename(html_file.split("/")[-1])
    parsed_data = parse_xcuitest_html(html_file)
    
    with open(output_ndjson, "w", encoding="utf-8") as file:
        for suite in parsed_data:
            for test in suite.get("test_cases", []):
                test_entry = {
                    "branch": metadata.get("branch", "unknown"),
                    "suite": metadata.get("suite", "unknown"),
                    "device": metadata.get("device", "unknown"),
                    "timestamp": metadata.get("timestamp", "unknown"),
                    "test_suite": suite["name"],
                    "test_case": test["name"],
                    "execution_time_s": test["execution_time"],
                    "result": test["result"]
                }
                json.dump(test_entry, file)
                file.write("\n")
    
    print(f"✅ NDJSON file created: {output_ndjson}")

if __name__ == "__main__":
    try:
        print("Starting HTML to JSON conversion for:", sys.argv[1])
        if len(sys.argv) != 3:
            print("Usage: python convert_xcuitest_to_ndjson.py <path_to_html_file> <output_ndjson_file>")
            sys.exit(1)
    
        html_file = sys.argv[1]
        output_ndjson = sys.argv[2]
    
        convert_to_ndjson(html_file, output_ndjson)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)  # Ensure the script exits with an error code
