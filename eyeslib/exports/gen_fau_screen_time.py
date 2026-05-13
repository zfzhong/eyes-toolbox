import pandas as pd
import argparse
import sys

def process_fau(input_file, statuses, duration_mode, output_file):
    # 1. Load Data
    df = pd.read_csv(input_file)
    
    # STEP 1: Filter by device_status
    df = df[df['device_status'].isin(statuses)].copy()
    
    # STEP 2: Filter by duration type
    # 'duration' column = primary, 'secondary_duration' column = secondary
    if duration_mode == 'primary':
        df = df[df['duration'] > 0].copy()
    elif duration_mode == 'secondary':
        df = df[df['secondary_duration'] > 0].copy()
    # If mode is 'both' or omitted, we keep rows where either/both > 0

    if df.empty:
        print("No rows matched the specified filters.")
        return

    # STEP 3: Sort by resume_time
    df = df.sort_values(by='resume_time').reset_index(drop=True)

    # STEP 4: Merge consecutive rows
    combined_rows = []
    current_row = df.iloc[0].to_dict()
    
    for i in range(1, len(df)):
        next_row = df.iloc[i].to_dict()
        
        # Merge criteria: 
        # 1. Same app package 
        # 2. Perfect timestamp connection 
        # 3. Same device status
        if (current_row['app_package_name'] == next_row['app_package_name'] and 
            current_row['end_time'] == next_row['resume_time'] and
            current_row['device_status'] == next_row['device_status']):
            
            current_row['end_time'] = next_row['end_time']
            current_row['duration'] = round(current_row['duration'] + next_row['duration'], 3)
            current_row['secondary_duration'] = round(current_row['secondary_duration'] + next_row['secondary_duration'], 3)
        else:
            combined_rows.append(current_row)
            current_row = next_row
    
    # Don't forget the last processed row
    combined_rows.append(current_row)

    # Final Save
    final_df = pd.DataFrame(combined_rows)
    final_df.to_csv(output_file, index=False)
    print(f"Successfully processed {len(df)} rows into {len(final_df)} merged rows.")
    print(f"File saved to: {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Filter and Merge FAU usage data.")
    parser.add_argument("input", help="Input .fau.csv file")
    parser.add_argument("--statuses", nargs='+', required=True, help="Statuses to include (e.g. ACTIVE GAP)")
    parser.add_argument("--mode", choices=['primary', 'secondary', 'both'], default='both', 
                        help="Filter rows where specified duration > 0")
    parser.add_argument("--output", required=True, help="Output file path")

    args = parser.parse_args()
    process_fau(args.input, args.statuses, args.mode, args.output)