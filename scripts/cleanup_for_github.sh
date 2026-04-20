#!/bin/bash
# DAWN Pre-Push Cleanup Script
# Removes temporary files and test artifacts before pushing to GitHub

echo "🧹 Cleaning DAWN repository for GitHub push..."

# 1. Remove test projects
echo "Removing test projects..."
rm -rf projects/test_*

# 2. Remove Python cache files
echo "Removing Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type f -name "*.pyc" -delete
find . -type f -name "*.pyo" -delete

# 3. Remove macOS metadata
echo "Removing macOS metadata..."
find . -name ".DS_Store" -delete
find . -name "._*" -delete

# 4. Remove temporary test logs (keep final evidence)
echo "Cleaning test logs..."
cd tests
rm -f acceptance_final.log
rm -f acceptance_run_final.log
rm -f final_complete.log
rm -f final_evidence.log
rm -f final_run.log
rm -f test_c_final.log
rm -f FINAL_RUN.log
rm -f FINAL_WITH_EXCLUDES.log
rm -f COMPLETE_FINAL.log
# Keep: final_evidence_5of5.log (production evidence)
cd ..

# 5. Remove editor swap files
echo "Removing editor swap files..."
find . -name "*.swp" -delete
find . -name "*.swo" -delete
find . -name "*~" -delete

# 6. Remove backup files
echo "Removing backup files..."
find . -name "*.backup" -delete
find . -name "*.bak" -delete
find . -name "*.tmp" -delete

echo "✅ Cleanup complete!"
echo ""
echo "Files preserved:"
echo "  - tests/final_evidence_5of5.log (production evidence)"
echo "  - All source code and documentation"
echo "  - Example projects (calc_*, agent_*, app_mvp)"
echo ""
echo "Ready for: git add . && git commit && git push"
