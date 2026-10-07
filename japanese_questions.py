"""小1向けの固定80問。生成AIを使わず、問題と分析属性を一緒に管理します。"""

CATEGORIES = {
    "words": "ことば", "sentence": "1ぶんを よむ", "information": "だれ・なに・どこ",
    "sequence": "ぶんの じゅんばん", "passage": "みじかい おはなし", "blank": "ぶんの あなうめ",
}
TAG_LABELS = {
    "hiragana": "ひらがな", "vocabulary": "語彙", "antonym": "反対語", "word_group": "仲間の言葉",
    "subject": "主語", "predicate": "述語", "particle": "助詞", "sentence_understanding": "文意理解",
    "information": "情報抽出", "sequence": "時系列", "context": "文脈理解", "grammar": "文法",
    "reference": "指示語", "inference": "推測", "connection": "接続関係", "word_order": "語順",
    "sentence_creation": "文生成",
}
QUESTION_LABELS = {"who": "だれ", "what": "なに", "where": "どこ", "when": "いつ",
                   "action": "どうした", "why": "なぜ", "how": "どんな", "order": "順番",
                   "reference": "指示語", "match": "内容一致", "word": "ことば", "blank": "穴埋め"}
ERROR_LABELS = {
    "word_meaning": "言葉の意味の取り違えの可能性", "character": "文字の取り違えの可能性",
    "question_meaning": "質問語の取り違えの可能性", "find_answer": "文中の情報の取り違えの可能性",
    "subject": "主語の取り違えの可能性", "particle": "助詞の取り違えの可能性",
    "order": "前後関係の取り違えの可能性", "reference": "指示語の取り違えの可能性",
    "inference": "文をつなげる理解の課題の可能性", "context": "文脈の取り違えの可能性",
}


def build_questions():
    questions = []

    def add(category, text, question, choices, answer, tags, word="word", level=1,
            difficulty=1, hint="もういちど ゆっくり よんでみよう。", explanation="", errors=None,
            form="choice"):
        identifier = f"jp_{category}_{sum(q['category'] == category for q in questions) + 1:03}"
        questions.append({"question_id": identifier, "category": category, "problem_format": form,
                          "text": text, "question": question, "choices": choices, "answer": answer,
                          "skill_tags": tags, "question_word": word, "reasoning_level": level,
                          "difficulty": difficulty, "hint": hint, "explanation": explanation,
                          "error_tags": errors or {}, "version": 1})

    for word, choices in [("りんご", ["りんご", "りんこ", "りごん"]),
                          ("さかな", ["さかね", "さかな", "かなさ"]),
                          ("うさぎ", ["うきぎ", "うさき", "うさぎ"])]:
        add("words", word, "おなじ ことばを えらぼう。", choices, choices.index(word),
            ["hiragana"], hint="はじめから 1もじずつ くらべてね。",
            explanation=f"「{word}」と おなじ もじの ならびを さがすよ。",
            errors={str(i): ["character"] for i, value in enumerate(choices) if value != word})
    for text, choices, answer, full in [("り○ご", ["か", "ん", "ね"], 1, "りんご"),
                                        ("○さぎ", ["う", "あ", "え"], 0, "うさぎ"),
                                        ("さか○", ["に", "ぬ", "な"], 2, "さかな")]:
        add("words", text, "○に はいる もじは どれ？", choices, answer,
            ["hiragana", "vocabulary"], hint="たべものや いきものの なまえだよ。",
            explanation=f"「{full}」に なるよ。", errors={str(i): ["character"] for i in range(3) if i != answer})
    for text, choices, answer in [("おおきい", ["ながい", "ちいさい", "たかい"], 1),
                                  ("あつい", ["つめたい", "あかい", "はやい"], 0),
                                  ("ながい", ["ひろい", "おもい", "みじかい"], 2)]:
        add("words", text, "はんたいの いみの ことばは どれ？", choices, answer,
            ["vocabulary", "antonym"], hint="くらべたときに はんたいに なる ことばだよ。",
            explanation=f"「{text}」の はんたいは「{choices[answer]}」だよ。",
            errors={str(i): ["word_meaning"] for i in range(3) if i != answer})
    for text, choices, answer in [("いぬ・ねこ", ["えんぴつ", "うさぎ", "つくえ"], 1),
                                  ("りんご・みかん", ["ばなな", "くつ", "ぼうし"], 0),
                                  ("あか・あお", ["いす", "かさ", "きいろ"], 2)]:
        add("words", text, "おなじ なかまの ことばは どれ？", choices, answer,
            ["vocabulary", "word_group"], hint="どうぶつ・くだもの・いろの なかまを かんがえよう。",
            explanation=f"「{choices[answer]}」も おなじ なかまだよ。",
            errors={str(i): ["word_meaning"] for i in range(3) if i != answer})

    scenes = [
        ("たろうくん", "りんご", "たべました", "おかあさん"),
        ("みきちゃん", "ほん", "よみました", "おとうさん"),
        ("ゆうたくん", "ボール", "なげました", "いもうと"),
        ("あやちゃん", "はな", "かざりました", "おにいさん"),
    ]
    for name, obj, action, distractor in scenes:
        text = f"{name}は {obj}を {action}。"
        add("sentence", text, f"だれが {obj}を {action}か？", [obj, name, distractor], 1,
            ["subject", "sentence_understanding"], "who", hint="「は」の まえの なまえを みよう。",
            explanation=f"{name}が {action}。", errors={"0": ["subject"], "2": ["find_answer"]})
        add("sentence", text, f"{name}は なにを {action}か？", [obj, distractor, name], 0,
            ["particle", "information", "sentence_understanding"], "what",
            hint="「を」の まえの ことばを みよう。", explanation=f"{obj}を {action}。",
            errors={"1": ["find_answer"], "2": ["question_meaning"]})
        add("sentence", text, f"{name}は どうした？", ["ねました", "あるきました", action], 2,
            ["predicate", "sentence_understanding"], "action", hint="ぶんの おわりを みよう。",
            explanation=f"ぶんには「{action}」と かいてあるよ。",
            errors={"0": ["find_answer"], "1": ["find_answer"]})

    places = [("ゆうたくん", "こうえん", "サッカー", "きょう", "しました"),
              ("みきちゃん", "としょかん", "ほん", "きのう", "よみました"),
              ("たろうくん", "いえ", "え", "あさ", "かきました")]
    for name, place, obj, when, action in places:
        text = f"{when}、{name}は {place}で {obj}を {action}。"
        prompts = [
            ("who", "だれが", [obj, name, place], 1),
            ("what", "なにを", [when, place, obj], 2),
            ("where", "どこで", [place, obj, name], 0),
            ("when", "いつ", [obj, when, place], 1),
            ("action", "どうしましたか？", ["ねました", "たべました", action], 2),
            ("match", "ぶんと おなじ ことは どれ？", [f"{name}が {place}に いました。",
                                                       f"{obj}を たべました。", "うみで あそびました。"], 0),
        ]
        for word, prefix, choices, answer in prompts:
            question = prefix if word in ("action", "match") else f"{prefix} {action}か？"
            add("information", text, question, choices, answer, ["information", "sentence_understanding"],
                word, hint=f"「{QUESTION_LABELS[word]}」を きいているよ。ぶんから さがそう。",
                explanation=f"こたえは「{choices[answer]}」。ぶんと くらべてみよう。",
                errors={str(i): ["question_meaning" if word not in ("action", "match") else "find_answer"]
                        for i in range(3) if i != answer})

    sequences = [
        ["あさごはんを たべました", "くつを はきました", "いえを でました"],
        ["たねを まきました", "めが でました", "はなが さきました"],
        ["てを あらいました", "ごはんを たべました", "はを みがきました"],
        ["かばんを あけました", "ほんを だしました", "ほんを よみました"],
        ["かみを よういしました", "えを かきました", "えを かざりました"],
        ["くつを はきました", "こうえんへ いきました", "ブランコに のりました"],
        ["コップを だしました", "みずを いれました", "みずを のみました"],
        ["ほんを かりました", "いえで よみました", "ほんを かえしました"],
        ["はなを つみました", "かびんに いれました", "つくえに かざりました"],
        ["あめが ふりました", "かさを さしました", "そとへ でました"],
    ]
    for index, events in enumerate(sequences):
        order = ([1, 2, 0], [2, 0, 1], [2, 1, 0])[index % 3]
        choices = [events[i] for i in order]
        add("sequence", f"はじめに、{events[0]}。つぎに、{events[1]}。さいごに、{events[2]}。",
            "おはなしの じゅんばんに ならべよう。", choices,
            [order.index(i) for i in range(3)], ["sequence", "context"], "order", level=2,
            hint="はじめに → つぎに → さいごに、を さがそう。",
            explanation=" → ".join(events), form="ordering", errors={"ordering": ["order"]})

    stories = [
        ("みきちゃんは こうえんへ いきました。\nこうえんには ねこが いました。\nみきちゃんは ねこを みました。",
         [("みきちゃんが みたものは なに？", ["ねこ", "いぬ", "とり"], 0, "what", ["information"], 2),
          ("ねこは どこに いましたか？", ["いえ", "こうえん", "がっこう"], 1, "where", ["information"], 2),
          ("こうえんへ いったのは だれ？", ["ねこ", "おとうさん", "みきちゃん"], 2, "who", ["subject"], 1)]),
        ("あめが ふっていました。\nゆうたくんは ぬれないように かさを もちました。",
         [("なぜ かさを もちましたか？", ["はれたから", "あめで ぬれないように", "ほんを よむため"], 1, "why", ["connection"], 2),
          ("ゆうたくんが もったものは なに？", ["かさ", "ボール", "ほん"], 0, "what", ["information"], 1),
          ("てんきは どうでしたか？", ["ゆき", "はれ", "あめ"], 2, "how", ["vocabulary"], 1)]),
        ("あやちゃんは りんごを かいました。\nそれを いえで たべました。",
         [("「それ」は なに？", ["いえ", "あやちゃん", "りんご"], 2, "reference", ["reference"], 2),
          ("どこで たべましたか？", ["いえ", "みせ", "こうえん"], 0, "where", ["information"], 2),
          ("あやちゃんが はじめに したことは？", ["りんごを たべた", "りんごを かった", "ねた"], 1, "order", ["sequence"], 2)]),
        ("たろうくんは あさ、はなに みずを あげました。\nゆうがたにも みずを あげました。\nはなは げんきに なりました。",
         [("あさ、なにを しましたか？", ["ほんを よんだ", "みずを あげた", "ごはんを たべた"], 1, "action", ["information"], 2),
          ("みずを あげたのは いつ？", ["よるだけ", "あさだけ", "あさと ゆうがた"], 2, "when", ["information"], 3),
          ("はなは どうなりましたか？", ["げんきに なった", "ちいさく なった", "かれた"], 0, "how", ["sentence_understanding"], 1)]),
        ("りなちゃんは おなかが すきました。\nおかあさんが おにぎりを つくりました。\nりなちゃんは それを たべました。",
         [("おにぎりを つくったのは だれ？", ["りなちゃん", "おかあさん", "おとうさん"], 1, "who", ["subject"], 2),
          ("「それ」は なに？", ["おかあさん", "りなちゃん", "おにぎり"], 2, "reference", ["reference"], 2),
          ("りなちゃんは なぜ たべましたか？", ["おなかが すいたから", "さむいから", "ねむいから"], 0, "why", ["inference", "context"], 3)]),
        ("けんくんは ともだちと あそぶ やくそくを しました。\nともだちが きたので、けんくんは にこにこ しました。",
         [("けんくんと やくそくしたのは だれ？", ["せんせい", "おかあさん", "ともだち"], 2, "who", ["information"], 2),
          ("けんくんは どんな かおに なりましたか？", ["にこにこ", "おこった かお", "ないた かお"], 0, "how", ["vocabulary"], 1),
          ("けんくんは どんな きもちでしょう？", ["かなしい", "うれしい", "こわい"], 1, "how", ["inference"], 4)]),
    ]
    for text, items in stories:
        for question, choices, answer, word, tags, level in items:
            cause = "reference" if word == "reference" else "inference" if level >= 3 else "find_answer"
            add("passage", text, question, choices, answer, ["sentence_understanding", *tags], word,
                level=level, difficulty=2 if level >= 3 else 1,
                hint="しつもんを よんでから、おはなしの どのぶんに あるか さがしてみよう。",
                explanation=f"おはなしから かんがえると「{choices[answer]}」だよ。",
                errors={str(i): [cause] for i in range(3) if i != answer})

    blanks = [
        ("わたしは あさ ○○を たべます。", ["はしる", "ごはん", "あおい"], 1, ["vocabulary", "grammar"]),
        ("ねこが ○○と なきました。", ["にゃあ", "わん", "こけこっこー"], 0, ["vocabulary", "context"]),
        ("ほん○ よみます。", ["に", "で", "を"], 2, ["particle", "grammar"]),
        ("こうえん○ あそびます。", ["を", "で", "が"], 1, ["particle", "grammar"]),
        ("がっこう○ いきます。", ["へ", "を", "が"], 0, ["particle", "grammar"]),
        ("あめが ふりました。○○、かさを さしました。", ["でも", "ところが", "だから"], 2, ["connection", "context"]),
        ("ごはんを たべました。○○、はを みがきました。", ["でも", "そして", "なぜなら"], 1, ["connection", "sequence"]),
        ("さむいので、○○を きました。", ["うわぎ", "くつ", "かさ"], 0, ["vocabulary", "context"]),
        ("のどが かわいたので、みずを ○○。", ["かきました", "はきました", "のみました"], 2, ["predicate", "vocabulary"]),
        ("あかい ○○が さきました。", ["くつ", "はな", "ほん"], 1, ["vocabulary", "context"]),
    ]
    for text, choices, answer, tags in blanks:
        cause = "particle" if "particle" in tags else "context"
        add("blank", text, "○に はいる ことばは どれ？", choices, answer, tags, "blank",
            hint="ことばを いれて、ぶんを はじめから よんでみよう。",
            explanation=text.replace("○○", choices[answer]).replace("○", choices[answer]),
            errors={str(i): [cause] for i in range(3) if i != answer})
    return questions


QUESTIONS = build_questions()
