"""The input of bench/wordfreq: a text of made-up words, the same every time.

    python3 bench/words.py WORDS > text.txt

Words come from a vocabulary of 20,000, made of syllables; the choice is
skewed, as in real text, so that a few words are very common. Python's
seeded Mersenne Twister makes it the same everywhere: `random()` gives the
same sequence for a seed on every version.
"""
import random
import sys

SYLLABLES = ["ka", "lo", "mi", "ne", "ru", "sa", "ti", "vo", "zen", "pra", "dul", "fo", "gri", "he", "ja", "qu"]


def main() -> None:
    words = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    rng = random.Random(12345)

    def pick(n: int) -> int:
        return int(rng.random() * n)

    vocab = []
    for _ in range(20000):
        vocab.append("".join(SYLLABLES[pick(len(SYLLABLES))] for _ in range(1 + pick(4))))
    out = []
    line = []
    for _ in range(words):
        u = rng.random()
        line.append(vocab[int(len(vocab) * u * u * u)])
        if len(line) == 12:
            out.append(" ".join(line))
            line = []
    if line:
        out.append(" ".join(line))
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
