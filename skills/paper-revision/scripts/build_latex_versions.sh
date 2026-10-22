#!/usr/bin/env bash
# Build the red-marked and the clean PDF from one LaTeX source that marks revisions with \rev{} / revblock
# (assets/revmarks.tex), then check the pair.
#
# Usage: build_latex_versions.sh MAIN.tex OUTDIR [pdflatex|xelatex|lualatex]
# Outputs: OUTDIR/<stem>_marked.pdf, OUTDIR/<stem>_clean.pdf, OUTDIR/<stem>_{marked,clean}.txt
# Checks:  the source loads revmarks (or defines \rev); no hard-coded red (outside comments) in any project .tex file
#          either build actually read (latexmk .fls of both builds, so \input sub-files, files outside the main
#          directory and clean-only branches count, unrelated .tex files do not) — it would stay red in the clean
#          PDF; both PDFs carry identical text (pdftotext).
# Exit:    0 = both PDFs built and checks passed; 1 = build or check failed; 2 = bad arguments.
set -euo pipefail

if [[ $# -lt 2 ]]; then sed -n '2,10p' "$0"; exit 2; fi
main=$(realpath "$1"); out=$(realpath -m "$2"); engine=${3:-pdflatex}
[[ -f $main ]] || { echo "ERROR: $main not found" >&2; exit 2; }
case $engine in
  pdflatex) flag=-pdf ;; xelatex) flag=-pdfxe ;; lualatex) flag=-pdflua ;;
  *) echo "ERROR: engine must be pdflatex, xelatex or lualatex" >&2; exit 2 ;;
esac
dir=$(dirname "$main"); stem=$(basename "$main" .tex)
mkdir -p "$out"
cd "$dir"

status=0
if ! grep -Eq '\\input\{revmarks(\.tex)?\}|\\newcommand\{?\\rev\}?' "$main"; then
  echo "ERROR: $main neither inputs revmarks.tex nor defines \\rev" >&2; exit 1
fi

common=(-recorder -interaction=nonstopmode -halt-on-error -file-line-error -outdir="$out")
latexmk "$flag" "${common[@]}" -jobname="${stem}_marked" "$stem.tex" > "$out/${stem}_marked.build.log" 2>&1 \
  || { echo "ERROR: marked build failed, see $out/${stem}_marked.build.log" >&2; exit 1; }
latexmk "$flag" "${common[@]}" -usepretex='\def\cleanversion{}' -jobname="${stem}_clean" "$stem.tex" > "$out/${stem}_clean.build.log" 2>&1 \
  || { echo "ERROR: clean build failed, see $out/${stem}_clean.build.log" >&2; exit 1; }

# project .tex files read by either build (union of both .fls recorder files). TeX distribution files are skipped;
# project files outside the main directory (e.g. ../shared/results.tex) are included.
srcs=(); declare -A seen=()
for fls in "$out/${stem}_marked.fls" "$out/${stem}_clean.fls"; do
  [[ -f $fls ]] || { echo "WARN: $fls missing; its inputs are not scanned"; continue; }
  while IFS= read -r f; do
    [[ $f = /* ]] || f="$dir/${f#./}"
    f=$(realpath -m "$f")
    [[ $f == *.tex && -f $f && $(basename "$f") != revmarks.tex && -z ${seen[$f]:-} ]] || continue
    case $f in /usr/*|/opt/*|/etc/*|*/texmf*|*/texlive/*) continue ;; esac
    seen[$f]=1; srcs+=("$f")
  done < <(awk '/^INPUT /{sub(/^INPUT /,""); print}' "$fls")
done
[[ ${#srcs[@]} -gt 0 ]] || srcs=("$main")
nrev=$(cat "${srcs[@]}" | grep -o '\\rev{' | wc -l || true)
nblock=$(cat "${srcs[@]}" | grep -o '\\begin{revblock}' | wc -l || true)
stray=$(grep -nE '\\(textcolor|color)\{red\}' "${srcs[@]}" /dev/null | grep -vE '^[^:]+:[0-9]+:[[:space:]]*%' || true)
if [[ -n $stray ]]; then
  echo "WARN: hard-coded red outside \\rev (stays red in the clean PDF):"; echo "$stray"; status=1
fi

pdftotext -layout "$out/${stem}_marked.pdf" "$out/${stem}_marked.txt"
pdftotext -layout "$out/${stem}_clean.pdf" "$out/${stem}_clean.txt"
if cmp -s "$out/${stem}_marked.txt" "$out/${stem}_clean.txt"; then same=true; else same=false; status=1; fi
pages_m=$(pdfinfo "$out/${stem}_marked.pdf" | awk '/^Pages:/{print $2}')
pages_c=$(pdfinfo "$out/${stem}_clean.pdf" | awk '/^Pages:/{print $2}')
printf '{"sources_scanned": %s, "rev_marks": %s, "revblocks": %s, "texts_identical": %s, "pages_marked": %s, "pages_clean": %s, "marked": "%s", "clean": "%s"}\n' \
  "${#srcs[@]}" "$nrev" "$nblock" "$same" "$pages_m" "$pages_c" "$out/${stem}_marked.pdf" "$out/${stem}_clean.pdf"
exit $status
