import pandas as pd
import argparse
import sys

# ==========================================
# GLOBAL SETTINGS
# ==========================================
EXCLUDE_LIST = [
    'Activity Resumed', 'Activity Paused', 'Activity Stopped',
    'Unknown importance: 23', 'Move to Foreground', 'Move to Background'
]

def merge_timeline(chronicle_path, fau_path, output_path):
    try:
        # 1. Load Data
        df_chron = pd.read_csv(chronicle_path)
        df_fau = pd.read_csv(fau_path)
        
        # 2. Enrich FAU file with interaction_type
        df_fau['interaction_type'] = 'App Usage'
        
        # 3. Filter and Rename Chronicle Columns
        df_chron = df_chron[~df_chron['interaction_type'].isin(EXCLUDE_LIST)].copy()
        df_chron = df_chron.rename(columns={
            'event_timestamp': 'resume_time',
            'application_label': 'app_label'
        })
        
        # 4. Standardize Timestamps to UTC
        df_chron['resume_time'] = pd.to_datetime(df_chron['resume_time'], utc=True, format='ISO8601')
        df_fau['resume_time'] = pd.to_datetime(df_fau['resume_time'], utc=True, format='ISO8601')
        if 'end_time' in df_fau.columns:
            df_fau['end_time'] = pd.to_datetime(df_fau['end_time'], utc=True, format='ISO8601')
        
        # 5. Strict Column Alignment
        # The final set of columns is defined by the modified FAU file
        fau_cols = df_fau.columns.tolist()
        
        # Instead of generic NA, we initialize with types that match the FAU file
        for col in fau_cols:
            if col not in df_chron.columns:
                # Create the column with the same dtype as found in df_fau
                df_chron[col] = pd.Series(dtype=df_fau[col].dtype)
        
        # Drop extra Chronicle columns so it matches FAU exactly
        df_chron = df_chron[fau_cols]

        # Ensure interaction_type in FAU matches Chronicle's type (usually object/string)
        if 'interaction_type' not in df_fau.columns:
            df_fau['interaction_type'] = 'App Usage'
            df_fau['interaction_type'] = df_fau['interaction_type'].astype(df_chron['interaction_type'].dtype)
        
        # 6. Merge and Interleave
        # Since both are sorted, mergesort is efficient and keeps relative order stable
        merged = pd.concat([df_chron, df_fau], ignore_index=True)
        merged = merged.sort_values(by='resume_time', kind='mergesort').reset_index(drop=True)
        
        # 7. Final String Formatting (UTC)
        def to_utc_str(ts):
            if pd.isna(ts) or ts is pd.NaT: return ts
            return ts.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + '+00:00'

        merged['resume_time'] = merged['resume_time'].apply(to_utc_str)
        if 'end_time' in merged.columns:
            merged['end_time'] = merged['end_time'].apply(to_utc_str)
            
        # 8. Save
        merged.to_csv(output_path, index=False)
        print(f"Merge Complete: {len(merged)} rows saved to {output_path}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge Chronicle and FAU data into a unified UTC timeline.")
    parser.add_argument("chronicle", help="Path to input Chronicle CSV")
    parser.add_argument("fau", help="Path to input FAU CSV")
    parser.add_argument("output", help="Path for the output merged CSV")
    args = parser.parse_args()
    merge_timeline(args.chronicle, args.fau, args.output)