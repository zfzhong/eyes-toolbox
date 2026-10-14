import pandas as pd
import sys
from pathlib import Path

def process_and_split(chunk_file, block_file, duration_threshold=5):
    # 1. Load Data
    try:
        df_chunks = pd.read_csv(chunk_file)
        df_blocks = pd.read_csv(block_file)
    except Exception as e:
        print(f"Error loading files: {e}")
        return

    start_col = 'resume_time'
    
    # 2. Pre-process Chunks: Filter out rows where both duration fields are 0
    df_chunks = df_chunks[~((df_chunks['duration'] == 0) & (df_chunks['secondary_duration'] == 0))].copy()

    # 3. Pre-process Blocks: Drop partials and handle duration threshold
    df_blocks = df_blocks.dropna(subset=['start_ts', 'end_ts'])
    df_blocks['start_dt'] = pd.to_datetime(df_blocks['start_ts'], format='ISO8601', errors='coerce')
    df_blocks['end_dt'] = pd.to_datetime(df_blocks['end_ts'], format='ISO8601', errors='coerce')
    df_blocks = df_blocks.dropna(subset=['start_dt', 'end_dt'])
    
    # Filter blocks by duration threshold (e.g., 5 seconds)
    df_blocks['block_dur'] = (df_blocks['end_dt'] - df_blocks['start_dt']).dt.total_seconds()
    df_blocks = df_blocks[df_blocks['block_dur'] >= duration_threshold].copy()

    # 4. Parse Chunk Datetimes
    df_chunks['start_dt'] = pd.to_datetime(df_chunks[start_col], format='ISO8601', errors='coerce')
    df_chunks['end_dt'] = pd.to_datetime(df_chunks['end_time'], format='ISO8601', errors='coerce')
    df_chunks = df_chunks.dropna(subset=['start_dt', 'end_dt'])

    # 5. Sort for Two-Pointer Logic
    df_chunks = df_chunks.sort_values('start_dt').reset_index(drop=True)
    df_blocks = df_blocks.sort_values('start_dt').reset_index(drop=True)

    chunks = df_chunks.to_dict('records')
    blocks = df_blocks.to_dict('records')

    results = []

    # Chunks overlap each other (primary vs secondary rows), so the block
    # pointer cannot be carried monotonically from one chunk to the next.
    # For each chunk, start at the first block whose running-max end_ts is
    # past the chunk start (blocks are sorted by start and may overlap).
    import bisect
    max_end = []
    running = None
    for blk in blocks:
        running = blk['end_dt'] if running is None or blk['end_dt'] > running else running
        max_end.append(running)

    c_idx = 0
    b_idx = 0
    positioned_for = -1

    # 6. Iterative Splitting Logic
    while c_idx < len(chunks):
        chunk = chunks[c_idx]
        c_start, c_end = chunk['start_dt'], chunk['end_dt']

        if positioned_for != c_idx:
            positioned_for = c_idx
            b_idx = bisect.bisect_right(max_end, c_start)

        if b_idx >= len(blocks):
            new_c = chunk.copy()
            new_c.update({'start_dt': c_start, 'end_dt': c_end, 'device_status': 'ACTIVE'})
            results.append(new_c)
            c_idx += 1
            continue

        block = blocks[b_idx]
        b_start, b_end = block['start_dt'], block['end_dt']

        if b_end <= c_start:
            b_idx += 1
        elif b_start >= c_end:
            new_c = chunk.copy()
            new_c.update({'start_dt': c_start, 'end_dt': c_end, 'device_status': 'ACTIVE'})
            results.append(new_c)
            c_idx += 1
        else:
            if c_start < b_start:
                # Segment before block
                new_c = chunk.copy()
                new_c.update({'start_dt': c_start, 'end_dt': b_start, 'device_status': 'ACTIVE'})
                results.append(new_c)
                chunk['start_dt'] = b_start
            else:
                # Segment matching block
                overlap_end = min(c_end, b_end)
                new_c = chunk.copy()
                new_c.update({'start_dt': c_start, 'end_dt': overlap_end, 'device_status': block['block_type']})
                results.append(new_c)
                
                if c_end > b_end:
                    chunk['start_dt'] = b_end
                    b_idx += 1
                else:
                    c_idx += 1

    # 7. Final Formatting and Duration Update Logic (Rounding to 3 decimals)
    if not results: return
    final_df = pd.DataFrame(results)
    
    def update_durations(row):
        total_sub_len = round((row['end_dt'] - row['start_dt']).total_seconds(), 3)
        if row['duration'] > 0:
            row['duration'], row['secondary_duration'] = total_sub_len, 0
        elif row['secondary_duration'] > 0:
            row['duration'], row['secondary_duration'] = 0, total_sub_len
        else:
            print(f"Warning: Chunk for {row['app_package_name']} at {row['start_dt']} "
                  f"has two zero-duration field. Setting both to 0.")
            row['duration'], row['secondary_duration'] = 0, 0
        return row

    final_df = final_df.apply(update_durations, axis=1)
    final_df[start_col], final_df['end_time'] = final_df['start_dt'], final_df['end_dt']
    
    output_cols = [c for c in df_chunks.columns if c not in ['start_dt', 'end_dt']] + ['device_status']
    final_df = final_df[output_cols]

    # 8. Output
    chunk_path = Path(chunk_file)
    output_file = chunk_path.parent / chunk_path.name.replace('_nested.csv', '_fau.csv')
    final_df.to_csv(output_file, index=False)
    print(f"Success! Saved to: {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python merge_app_status_fau.py <chunk_file> <block_file> [threshold]")
    else:
        threshold = int(sys.argv[3]) if len(sys.argv) > 3 else 5
        process_and_split(sys.argv[1], sys.argv[2], threshold)