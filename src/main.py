"""CLI entry point for BMTNews."""

import argparse
import asyncio
import sys
from datetime import date as date_type
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from .orchestrator import BMTNewsOrchestrator
from .storage.manager import ConfigError, StorageManager


console = Console()


def _edition_date(value: str) -> date_type:
    try:
        return date_type.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "edition date must use YYYY-MM-DD"
        ) from exc


def print_banner():
    """Print the application banner."""
    banner = r"""
[bold blue]
  ____  __  __ _____ _   _
 | __ )|  \/  |_   _| \ | | _____      _____
 |  _ \| |\/| | | | |  \| |/ _ \ \ /\ / / __|
 | |_) | |  | | | | | |\  |  __/\ V  V /\__ \
 |____/|_|  |_| |_| |_| \_|\___| \_/\_/ |___/
[/bold blue]
[cyan]  Daily crypto market, AI, and policy intelligence[/cyan]
    """
    console.print(banner)


def main():
    """Main CLI entry point."""
    print_banner()

    parser = argparse.ArgumentParser(description="BMTNews - AI-Driven Information Aggregation System")
    parser.add_argument("--hours", type=int, help="Force fetch from last N hours")
    parser.add_argument(
        "--mode",
        choices=("full", "fetch", "publish", "weekly", "x-post"),
        default="full",
        help=(
            "full runs the legacy pipeline; fetch only updates the staging cache; "
            "publish builds one fixed-window daily edition; "
            "weekly builds the weekly review from the archive; "
            "x-post publishes the next drip story for today's edition"
        ),
    )
    parser.add_argument(
        "--staging-path",
        type=Path,
        default=Path("data/staging-items.json"),
        help="Cross-run raw item staging file",
    )
    parser.add_argument(
        "--cutoff-hour",
        type=int,
        default=8,
        help="Daily edition cutoff hour in filtering.daily_timezone",
    )
    parser.add_argument(
        "--edition-date",
        type=_edition_date,
        default=None,
        help=(
            "Explicit local date whose fixed edition window should be built; "
            "only valid with --mode publish"
        ),
    )
    parser.add_argument(
        "--force-publish",
        action="store_true",
        help="Rebuild an edition even when that fixed window is already published",
    )
    parser.add_argument(
        "--x-kickoff-only",
        action="store_true",
        help=(
            "Post the first X story only when the edition queue has not started; "
            "requires --mode x-post"
        ),
    )
    args = parser.parse_args()
    if args.hours is not None and args.hours <= 0:
        parser.error("--hours must be positive")
    if not 0 <= args.cutoff_hour <= 23:
        parser.error("--cutoff-hour must be between 0 and 23")
    if args.force_publish and args.mode != "publish":
        parser.error("--force-publish requires --mode publish")
    if args.x_kickoff_only and args.mode != "x-post":
        parser.error("--x-kickoff-only requires --mode x-post")
    if args.edition_date is not None and args.mode not in {
        "publish",
        "weekly",
        "x-post",
    }:
        parser.error(
            "--edition-date requires --mode publish, --mode weekly, or --mode x-post"
        )

    try:
        # Load environment variables from .env file
        load_dotenv()

        # Ensure we're in the project directory or use data/ in current dir
        data_dir = Path("data")

        # Initialize storage manager
        storage = StorageManager(data_dir=str(data_dir))

        # Load configuration
        try:
            config = storage.load_config()
        except FileNotFoundError:
            console.print("[bold red]❌ Configuration file not found![/bold red]\n")
            data_dir_path = data_dir if isinstance(data_dir, Path) else Path(data_dir)
            example_path = data_dir_path / "config.example.json"
            if example_path.exists():
                console.print(
                    f"Copy the example config and edit it:\n"
                    f"  [cyan]cp {example_path} {data_dir_path / 'config.json'}[/cyan]\n"
                )
            console.print(
                "Or run [bold cyan]uv run bmtnews-wizard[/bold cyan] to launch the interactive setup wizard.\n"
            )
            sys.exit(1)
        except ConfigError as e:
            console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[bold red]❌ Error loading configuration: {e}[/bold red]")
            sys.exit(1)

        # Create and run orchestrator
        orchestrator = BMTNewsOrchestrator(config, storage)
        if args.mode == "fetch":
            asyncio.run(
                orchestrator.fetch_to_staging(
                    force_hours=args.hours,
                    staging_path=args.staging_path,
                )
            )
        elif args.mode == "x-post":
            asyncio.run(
                orchestrator.run_x_slot(
                    edition_date=args.edition_date,
                    kickoff_only=args.x_kickoff_only,
                )
            )
        elif args.mode == "weekly":
            asyncio.run(
                orchestrator.run_weekly_review(end_date=args.edition_date)
            )
        elif args.mode == "publish":
            asyncio.run(
                orchestrator.run_daily_edition(
                    force_hours=args.hours,
                    staging_path=args.staging_path,
                    cutoff_hour=args.cutoff_hour,
                    edition_date=args.edition_date,
                    force_publish=args.force_publish,
                )
            )
        else:
            asyncio.run(orchestrator.run(force_hours=args.hours))

    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]❌ Fatal error: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def print_config_template():
    """Print configuration template."""
    template = """
{
  "version": "1.0",
  "ai": {
    "provider": "anthropic",
    "model": "claude-sonnet-4.5-20250929",
    "api_key_env": "ANTHROPIC_API_KEY",
    "temperature": 0.3,
    "max_tokens": 4096
  },
  "sources": {
    "github": [
      {
        "type": "user_events",
        "username": "torvalds",
        "enabled": true
      }
    ],
    "hackernews": {
      "enabled": true,
      "fetch_top_stories": 30,
      "min_score": 100
    },
    "rss": [
      {
        "name": "Example Blog",
        "url": "https://example.com/feed.xml",
        "enabled": true,
        "category": "software-engineering"
      }
    ]
  },
  "filtering": {
    "ai_score_threshold": 7.0,
    "time_window_hours": 24,
    "daily_timezone": "UTC",
    "preserve_daily_items": false,
    "max_items": null,
    "category_groups": {},
    "default_group": "other",
    "default_group_limit": null,
    "primary_groups": [],
    "primary_group_min_items": null
  }
}

Also create a .env file with:
ANTHROPIC_API_KEY=your_api_key_here
GITHUB_TOKEN=your_github_token_here (optional but recommended)
"""
    console.print(template)


if __name__ == "__main__":
    main()
