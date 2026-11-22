# Historical Microsoft Tag fixtures

**This directory is intentionally empty.** No independently sourced original Microsoft Tag images were
available in the build environment (Wikipedia/Wikimedia, Google Patents and the 2009 istartedsomething
article were unreachable from the sandbox; the Microsoft Research page only shows generic HCCB samples).

To test historical compatibility:

1. Put original Microsoft Tag images here (scans/photos of printed tags, screenshots of
   tag.microsoft.com output, archived marketing material). Record provenance in `sources.json`:
   `{"file.jpg": {"source": "URL or description", "expected_tag_id": "00001_0000009692" or null}}`.
2. Run `cd backend && python -m pytest tests/test_fixtures.py -v`.

Interpretation:
* A decode that passes CRC16-X25 **and** RS **and** the filler/calibration check on an original image is
  strong evidence the reverse-engineered format is right (chance of a random pass ≈ 1e-8).
* If `expected_tag_id` is known (e.g. printed next to the tag), the test also asserts equality.
* A failure may be a detector/geometry mismatch rather than a codec error. Use
  `python hccb_cli.py decode file.jpg --debug-dir out/` and compare the rectified image with the original.
