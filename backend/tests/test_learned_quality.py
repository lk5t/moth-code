"""1.0: the learned quality filter prefers text that reads like the curated reference."""
import random

from moth.datafactory import quality_model as QM


def test_learned_quality_ranks_spam_below_good_text():
    rng = random.Random(0)
    good = ["The cat sat on the warm mat and looked out of the window at the birds in the garden.",
            "Water boils at one hundred degrees Celsius when the air pressure is normal at sea level.",
            "She opened the book, read the first page carefully and smiled at the story about the moon."]
    spam = ["best cheap deals click here buy now free shipping best price casino bonus win now click",
            "home | about | contact | login | register | terms | privacy | sitemap | home | about"]
    m = QM.QualityModel()
    for _ in range(300):
        m.add(rng.choice(good), True)
    for _ in range(300):
        m.add(rng.choice(good + spam * 2), False)
    m.fit()
    assert m.ready
    assert min(m.score(t) for t in good) > max(m.score(t) for t in spam)
    th = QM.threshold([m.score(t) for t in good + spam], 0.3)
    assert all(m.score(t) < th for t in spam[:1]) or all(m.score(t) <= th for t in spam)
