from scraper import run_scraper, load_results

def main():
    def progress(stage, page, posts_found, total_posts, current_title):
        if stage == "scraping":
            print(f"[page {page}] {posts_found} posts found so far...")
        elif stage == "dates":
            print(f"[dates {posts_found}/{total_posts}] {(current_title or '')[:70]}")
        elif stage == "analysis":
            print(f"[analysis {posts_found+1}/{total_posts}] {(current_title or '')[:70]}")

    print("Running scraper...")
    results = run_scraper(progress_callback=progress)
    print(f"\nDone. {len(results)} posts analysed and saved to results.json")

if __name__ == "__main__":
    main()
