import pandas as pd
import re
import sys

def get_timezone_blocks(chronicle_file):
    """Extracts sorted timezone blocks with UTC start/end boundaries."""
    df = pd.read_csv(chronicle_file)
    df['dt_utc'] = pd.to_datetime(df['event_timestamp'], errors='coerce', utc=True)
    df = df.dropna(subset=['dt_utc', 'timezone']).sort_values('dt_utc').reset_index(drop=True)

    def extract_offset(ts_str):
        match = re.search(r'([+-]\d{2}:?\d{2})$', str(ts_str))
        return match.group(1) if match else "+00:00"

    df['tz_offset'] = df['event_timestamp'].apply(extract_offset)
    
    # Identify changes
    df['change'] = (df['timezone'] != df['timezone'].shift()) | \
                   (df['tz_offset'] != df['tz_offset'].shift())
    df['block_id'] = df['change'].cumsum()

    # Aggregate blocks with boundaries
    blocks = df.groupby('block_id').agg(
        timezone=('timezone', 'first'),
        tz_offset=('tz_offset', 'first'),
        start_utc=('dt_utc', 'min'),
        end_utc=('dt_utc', 'max')
    ).sort_values('start_utc').to_dict('records')
    
    return blocks

def process_usage_sequentially(usage_file, blocks, output_file):
    """Processes sorted usage rows using a single pass through timezone blocks."""
    usage_df = pd.read_csv(usage_file)
    
    # Ensure they are datetime for comparison
    usage_df['resume_dt'] = pd.to_datetime(usage_df['resume_time'], errors='coerce', utc=True)
    usage_df['end_dt'] = pd.to_datetime(usage_df['end_time'], errors='coerce', utc=True)

    enriched_rows = []
    block_idx = 0
    num_blocks = len(blocks)

    for _, row in usage_df.iterrows():
        current_time = row['resume_dt']

        # Move the block pointer forward if the current usage row starts after the current block's end
        # We check (block_idx + 1) to ensure we don't go out of bounds
        while (block_idx + 1 < num_blocks) and (current_time > blocks[block_idx]['end_utc']):
            block_idx += 1
        
        active_block = blocks[block_idx]
        tz_name = active_block['timezone']
        
        # Prepare the enriched record
        record = row.to_dict()
        record['timezone'] = tz_name
        record['tz_offset'] = active_block['tz_offset']
        
        # Convert to local time
        if pd.notna(row['resume_dt']):
            record['local_resume_time'] = str(row['resume_dt'].tz_convert(tz_name))
        if pd.notna(row['end_dt']):
            record['local_end_time'] = str(row['end_dt'].tz_convert(tz_name))
            
        enriched_rows.append(record)

    # Convert to DataFrame and save
    final_df = pd.DataFrame(enriched_rows).drop(columns=['resume_dt', 'end_dt'])
    final_df.to_csv(output_file, index=False)
    return final_df

def main(chronicle_csv, usage_csv, output_csv):
    blocks = get_timezone_blocks(chronicle_csv)
    print(f"Extracted {len(blocks)} timezone blocks.")
    
    print(f"Enriching {usage_csv} sequentially...")
    final_df = process_usage_sequentially(usage_csv, blocks, output_csv)
    
    print(f"Done. Saved to {output_csv}")
    print(final_df[['resume_time', 'timezone', 'tz_offset', 'local_resume_time']].head())

if __name__ == "__main__":
    if len(sys.argv) == 4:
        main(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        print("Usage: python script.py <chronicle_file> <event_file> <output_file>")