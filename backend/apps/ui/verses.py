"""Rotating ESV Bible verses for the app footer (one per ISO week, 52/year).

Selection mixes stewardship/work/finance themes with the gospel so every week
has a fitting verse all year round. ESV text used by permission — keep the
attribution visible wherever a verse is rendered (partials/verse_footer.html).
"""

from datetime import date

# (reference, text) — order is fixed so week N always maps to the same verse.
ESV_VERSES = [
    ("Proverbs 3:9", "Honor the LORD with your wealth and with the firstfruits of all your produce."),
    ("Proverbs 11:1", "A false balance is an abomination to the LORD, but a just weight is his delight."),
    ("Proverbs 13:11", "Wealth gained hastily will dwindle, but whoever gathers little by little will increase it."),
    ("Proverbs 22:1", "A good name is to be chosen rather than great riches, and favor is better than silver or gold."),
    ("Proverbs 22:7", "The rich rules over the poor, and the borrower is the slave of the lender."),
    ("Proverbs 27:23–24", "Know well the condition of your flocks, and give attention to your herds, for riches do not last forever."),
    ("Proverbs 21:5", "The plans of the diligent lead surely to abundance, but everyone who is hasty comes only to poverty."),
    ("Proverbs 16:11", "A just balance and scales are the LORD's; all the weights in the bag are his work."),
    ("Malachi 3:10", "Bring the full tithe into the storehouse, that there may be food in my house."),
    ("Matthew 6:21", "For where your treasure is, there your heart will be also."),
    ("Matthew 6:33", "But seek first the kingdom of God and his righteousness, and all these things will be added to you."),
    ("Matthew 6:19–20", "Do not lay up for yourselves treasures on earth… but lay up for yourselves treasures in heaven."),
    ("Luke 6:38", "Give, and it will be given to you. Good measure, pressed down, shaken together, running over, will be put into your lap."),
    ("Luke 16:10", "One who is faithful in a very little is also faithful in much, and one who is dishonest in a very little is also dishonest in much."),
    ("Luke 14:28", "For which of you, desiring to build a tower, does not first sit down and count the cost, whether he has enough to complete it?"),
    ("Luke 16:11", "If then you have not been faithful in the unrighteous wealth, who will entrust to you the true riches?"),
    ("2 Corinthians 9:7", "Each one must give as he has decided in his heart, not reluctantly or under compulsion, for God loves a cheerful giver."),
    ("2 Corinthians 9:8", "And God is able to make all grace abound to you, so that having all sufficiency in all things at all times, you may abound in every good work."),
    ("1 Timothy 6:10", "For the love of money is a root of all kinds of evils. It is through this craving that some have wandered away from the faith."),
    ("1 Timothy 6:6", "But godliness with contentment is great gain."),
    ("Psalm 24:1", "The earth is the LORD's and the fullness thereof, the world and those who dwell therein."),
    ("Psalm 37:21", "The wicked borrows but does not pay back, but the righteous is generous and gives."),
    ("Psalm 112:5", "It is well with the man who deals generously and lends; who conducts his affairs with justice."),
    ("Psalm 90:12", "So teach us to number our days that we may get a heart of wisdom."),
    ("Proverbs 16:3", "Commit your work to the LORD, and your plans will be established."),
    ("Proverbs 10:4", "A slack hand causes poverty, but the hand of the diligent makes rich."),
    ("Proverbs 11:25", "Whoever brings blessing will be enriched, and one who waters will himself be watered."),
    ("Proverbs 11:28", "Whoever trusts in his riches will fall, but the righteous will flourish like a green leaf."),
    ("Proverbs 15:16", "Better is a little with the fear of the LORD than great treasure and trouble with it."),
    ("Proverbs 28:20", "A faithful man will abound with blessings, but whoever hastens to be rich will not go unpunished."),
    ("Proverbs 3:5–6", "Trust in the LORD with all your heart, and do not lean on your own understanding. In all your ways acknowledge him, and he will make straight your paths."),
    ("Colossians 3:23", "Whatever you do, work heartily, as for the Lord and not for men."),
    ("1 Corinthians 10:31", "So, whether you eat or drink, or whatever you do, do all to the glory of God."),
    ("Philippians 4:19", "And my God will supply every need of yours according to his riches in glory in Christ Jesus."),
    ("Philippians 4:13", "I can do all things through him who strengthens me."),
    ("Psalm 128:2", "You shall eat the fruit of the labor of your hands; you shall be blessed, and it shall be well with you."),
    ("Ecclesiastes 3:1", "For everything there is a season, and a time for every matter under heaven."),
    ("Ecclesiastes 9:10", "Whatever your hand finds to do, do it with your might."),
    ("Ecclesiastes 12:13", "The end of the matter; all has been heard. Fear God and keep his commandments, for this is the whole duty of man."),
    ("Genesis 1:1", "In the beginning, God created the heavens and the earth."),
    ("John 3:16", "For God so loved the world, that he gave his only Son, that whoever believes in him should not perish but have eternal life."),
    ("John 14:6", "Jesus said to him, \u201cI am the way, and the truth, and the life. No one comes to the Father except through me.\u201d"),
    ("Romans 5:8", "But God shows his love for us in that while we were still sinners, Christ died for us."),
    ("Romans 8:28", "And we know that for those who love God all things work together for good, for those who are called according to his purpose."),
    ("Romans 12:2", "Do not be conformed to this world, but be transformed by the renewal of your mind, that by testing you may discern what is the will of God."),
    ("1 Corinthians 15:57", "But thanks be to God, who gives us the victory through our Lord Jesus Christ."),
    ("Galatians 2:20", "I have been crucified with Christ. It is no longer I who live, but Christ who lives in me."),
    ("Ephesians 2:8–9", "For by grace you have been saved through faith. And this is not your own doing; it is the gift of God, not a result of works, so that no one may boast."),
    ("Philippians 2:3", "Do nothing from selfish ambition or conceit, but in humility count others more significant than yourselves."),
    ("James 1:17", "Every good gift and every perfect gift is from above, coming down from the Father of lights."),
    ("Hebrews 11:1", "Now faith is the assurance of things hoped for, the conviction of things not seen."),
    ("Revelation 21:4", "He will wipe away every tear from their eyes, and death shall be no more, neither shall there be mourning, nor crying, nor pain anymore."),
]

ESV_ATTRIBUTION = (
    "Scripture quotations are from The Holy Bible, English Standard Version® "
    "(ESV®), © 2001 by Crossway, a publishing ministry of Good News Publishers. "
    "Used by permission. All rights reserved."
)


def weekly_verse(*, today=None):
    """The featured verse for the current ISO week (52-week rotation)."""
    today = today or date.today()
    week = today.isocalendar()[1]  # 1..53
    ref, text = ESV_VERSES[(week - 1) % len(ESV_VERSES)]
    return {"week": week, "ref": ref, "text": text, "attribution": ESV_ATTRIBUTION}