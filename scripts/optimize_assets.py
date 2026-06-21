import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup, Comment

def clean_html_file(file_path: Path) -> str:
  """Strips layout styles, scripts, and attributes, keeping only semantic structural content."""
  html_content = file_path.read_text(encoding="utf-8", errors="replace")
  soup = BeautifulSoup(html_content, "html.parser")
  
  # 1. Remove script, style, head, header, footer, nav, iframe, svg, and metadata tags
  for element in soup(["script", "style", "head", "header", "footer", "nav", "iframe", "svg"]):
    element.decompose()
      
  # 2. Strip comments (using string= instead of text= for bs4 compatibility)
  for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
    comment.extract()
      
  # 3. Strip all style-related attributes (class, id, style, width, height, onload, etc.)
  # Keep only 'href' and 'src' attributes
  allowed_attributes = {"href", "src"}
  for tag in soup.find_all(True):
    attrs = dict(tag.attrs)
    for attr in attrs:
      if attr not in allowed_attributes:
        del tag.attrs[attr]
              
  # 4. Return compact HTML string with extra whitespaces normalized
  cleaned_html = str(soup)
  return "\n".join([line.strip() for line in cleaned_html.splitlines() if line.strip()])

def main():
  repo_root = Path(__file__).resolve().parent.parent
  pkg_data_dir = repo_root / "src" / "cms_kb" / "data"
  
  # 1. Optimize SQLite database
  db_path = pkg_data_dir / "index" / "retrieval.sqlite"
  if db_path.is_file():
    print(f"Optimizing SQLite index: {db_path} (size: {db_path.stat().st_size / 1024 / 1024:.2f}MB)")
    conn = sqlite3.connect(db_path)
    try:
      conn.execute("VACUUM;")
      conn.execute("PRAGMA optimize;")
      conn.commit()
      print("SQLite index optimized successfully.")
    except Exception as e:
      print(f"Error optimizing SQLite index: {e}")
    finally:
      conn.close()
    print(f"New SQLite index size: {db_path.stat().st_size / 1024 / 1024:.2f}MB")
      
  # 2. Clean up raw HTML files
  html_dir = pkg_data_dir / "raw" / "html"
  if html_dir.is_dir():
    print(f"Cleaning HTML files in: {html_dir}")
    cleaned_count = 0
    original_bytes = 0
    cleaned_bytes = 0
    for html_file in html_dir.rglob("*.html"):
      if html_file.is_file():
        try:
          orig_sz = html_file.stat().st_size
          cleaned_content = clean_html_file(html_file)
          html_file.write_text(cleaned_content, encoding="utf-8")
          new_sz = html_file.stat().st_size
          original_bytes += orig_sz
          cleaned_bytes += new_sz
          cleaned_count += 1
        except Exception as e:
          print(f"Error cleaning {html_file}: {e}")
    print(f"Cleaned {cleaned_count} HTML files.")
    if cleaned_count > 0:
      print(f"Original HTML size: {original_bytes / 1024 / 1024:.2f}MB, Cleaned HTML size: {cleaned_bytes / 1024 / 1024:.2f}MB")

if __name__ == "__main__":
  main()
