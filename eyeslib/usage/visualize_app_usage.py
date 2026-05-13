import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import sys

from datetime import date, timedelta

def enumerate_dates(start_date, end_date):
    """Generate all dates from start_date to end_date inclusive."""
    for n in range((end_date - start_date).days + 1):
        yield start_date + timedelta(days=n)

def visualize_app_usage(csv_path, output_dir):
    """
    Create app usage timeline for a given CSV.
    """
    try:
        df = pd.read_csv(csv_path)
        if not {"resume_time", "end_time", "app_label"}.issubset(df.columns):
            print(f"⚠️ Skipping {csv_path.name}: required columns missing.")
            return

        df["resume_time"] = pd.to_datetime(df["resume_time"], format='mixed')
        df["end_time"] = pd.to_datetime(df["end_time"], format='mixed')
        df["start_date"] = df["resume_time"].dt.date
        df["end_date"] = df["end_time"].dt.date

        df = df.sort_values("resume_time")

        # Prepare color map
        apps = df["app_label"].unique()
        color_map = {app: plt.cm.tab20(i % 20) for i, app in enumerate(apps)}
        unique_dates = sorted(df["start_date"].unique())

        start_date = unique_dates[0]
        end_date = unique_dates[-1]

        all_dates = list(enumerate_dates(start_date, end_date))

        h = max(len(apps), len(all_dates)) * 0.4
        fig, ax = plt.subplots(figsize=(16, h))

        for i, (day, group) in enumerate(df.groupby("start_date")):
            for _, row in group.iterrows():
                start = row["resume_time"]
                end = row["end_time"]
                width = (end - start).total_seconds() / 60  # duration in minutes
                start_min = start.hour * 60 + start.minute + start.second / 60

                j = (day - start_date).days 
                if start_min + width > 24*60:
                    # for duration passing midmight
                    width1 = 24*60 - start_min
                    width2 = width - width1
                    
                    ax.barh(j, width1, left=start_min, color=color_map[row["app_label"]], height=0.6)
                    ax.barh(j+1, width2, left=0, color=color_map[row["app_label"]], height=0.6)
                else:
                    ax.barh(j, width, left=start_min, color=color_map[row["app_label"]], height=0.6)

        ax.set_yticks(range(len(all_dates)))
        ax.set_yticklabels([str(d) for d in all_dates])

        ax.set_xticks([0, 180, 360, 540, 720, 900, 1080, 1260, 1440])
        ax.set_xticklabels(["00:00", "03:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "24:00"])

        ax.set_xlabel("Time of Day")
        ax.set_ylabel("Date")
        ax.set_title(f"App Usage Duration per Day: {csv_path.name}")
        ax.grid(True, axis="x", linestyle="--", alpha=0.4)

        # Legend
        handles = [plt.Rectangle((0, 0), 1, 1, color=color_map[app]) for app in apps]
        ax.legend(handles, apps, title="App Label", bbox_to_anchor=(1.01, 1), loc="upper left")

        plt.tight_layout()

        output_path = output_dir / f"{csv_path.stem}.png"
        plt.savefig(output_path, dpi=300)
        plt.close()

        print(f"✅ Saved: {output_path}")
    except Exception as e:
        print(f"❌ Error processing {csv_path.name}: {e}")

def batch_visualize(folder):
    """
    Process all CSV files in a given folder.
    """
    folder = Path(folder)
    output_dir = folder / "visual"
    output_dir.mkdir(exist_ok=True)

    csv_files = list(folder.glob("*_usage.csv"))
    if not csv_files:
        print("⚠️ No CSV files found in the folder.")
        return

    total = len(csv_files)
    print(f"🧭 Found {total} CSV files in {folder}:")
    for index, csv_file in enumerate(csv_files, start=1):
        print(f"[{index}/{total}] {csv_file.name}")
        visualize_app_usage(csv_file, output_dir)

    print(f"\n✅ All timelines saved in: {output_dir}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python batch_visualize_app_usage.py <folder_path>")
    else:
        batch_visualize(sys.argv[1]+'/processed')
