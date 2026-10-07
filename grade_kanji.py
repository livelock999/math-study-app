"""小学校学習指導要領の学年別漢字配当表を使う共通の表示判定。

平成29年告示・2020年度全面実施の1,026字。漢字の読み方や、
ひらがなからの変換は扱わず、文字が配当される学年だけを返す。
"""

from types import MappingProxyType

# 出典: 文部科学省「小学校学習指導要領（平成29年告示）解説 国語編」
# 付録3 別表（冊子192〜194頁 / PDF195〜197頁）、改訂点（冊子18頁）。
SOURCE_URL = "https://www.mext.go.jp/content/20220606-mxt_kyoiku02-100002607_002.pdf"
# 転記照合用: 文科省の旧1,006字表と上記公式資料18頁の追加20字・移行32字。
# https://www.mext.go.jp/a_menu/shotou/cs/1320015.htm
# 語の読み・音訓の習得学年を表すものではない。未習得の個別設定は表示側で扱う。
_GRADE_CHARACTERS = {
    1: (
        "一右雨円王音下火花貝学気九休玉金空月犬見五口校左三山子四糸字耳七車手十出女小上森"
        "人水正生青夕石赤千川先早草足村大男竹中虫町天田土二日入年白八百文木本名目立力林六"
    ),
    2: (
        "引羽雲園遠何科夏家歌画回会海絵外角楽活間丸岩顔汽記帰弓牛魚京強教近兄形計元言原戸"
        "古午後語工公広交光考行高黄合谷国黒今才細作算止市矢姉思紙寺自時室社弱首秋週春書少"
        "場色食心新親図数西声星晴切雪船線前組走多太体台地池知茶昼長鳥朝直通弟店点電刀冬当"
        "東答頭同道読内南肉馬売買麦半番父風分聞米歩母方北毎妹万明鳴毛門夜野友用曜来里理話"
    ),
    3: (
        "悪安暗医委意育員院飲運泳駅央横屋温化荷界開階寒感漢館岸起期客究急級宮球去橋業曲局"
        "銀区苦具君係軽血決研県庫湖向幸港号根祭皿仕死使始指歯詩次事持式実写者主守取酒受州"
        "拾終習集住重宿所暑助昭消商章勝乗植申身神真深進世整昔全相送想息速族他打対待代第題"
        "炭短談着注柱丁帳調追定庭笛鉄転都度投豆島湯登等動童農波配倍箱畑発反坂板皮悲美鼻筆"
        "氷表秒病品負部服福物平返勉放味命面問役薬由油有遊予羊洋葉陽様落流旅両緑礼列練路和"
    ),
    4: (
        "愛案以衣位印英栄塩億加果貨課芽改械害街各覚完官管関観願希季旗器機議求泣給挙漁共協"
        "鏡競極訓軍郡径景芸欠結建健験固功好候康差菜最材昨札刷察参産散残氏司試児治辞失借種"
        "周祝順初松笑唱焼照臣信成省清静席積折節説浅戦選然争倉巣束側続卒孫帯隊達単置仲兆低"
        "底的典伝徒努灯働特熱念敗梅博飯飛必票標不夫付府副兵別辺変便包法望牧末満未民無約勇"
        "要養浴利陸良料量輪類令冷例連老労録茨媛岡潟岐熊香佐埼崎滋鹿縄井沖栃奈梨阪阜賀群徳"
        "富城"
    ),
    5: (
        "圧移因永営衛易益液演応往桜可仮価河過快解格確額刊幹慣眼基寄規技義逆久旧居許境均禁"
        "句経潔件険検限現減故個護効厚耕鉱構興講混査再災妻採際在財罪雑酸賛支志枝師資飼示似"
        "識質舎謝授修述術準序招証条状常情織職制性政勢精製税責績接設絶祖素総造像増則測属率"
        "損貸態団断築張提程適統銅導独任燃能破犯判版比肥非備評貧布婦武復複仏編弁保墓報豊防"
        "貿暴務夢迷綿輸余容略留領囲紀喜救型航告殺士史象賞貯停堂得毒費粉脈歴"
    ),
    6: (
        "異遺域宇映延沿我灰拡革閣割株干巻看簡危机揮貴疑吸供胸郷勤筋系敬警劇激穴絹権憲源厳"
        "己呼誤后孝皇紅降鋼刻穀骨困砂座済裁策冊蚕至私姿視詞誌磁射捨尺若樹収宗就衆従縦縮熟"
        "純処署諸除将傷障蒸針仁垂推寸盛聖誠宣専泉洗染善奏窓創装層操蔵臓存尊宅担探誕段暖値"
        "宙忠著庁頂潮賃痛展討党糖届難乳認納脳派拝背肺俳班晩否批秘腹奮並陛閉片補暮宝訪亡忘"
        "棒枚幕密盟模訳郵優幼欲翌乱卵覧裏律臨朗論胃腸恩券承舌銭退敵俵預"
    ),
}

KANJI_BY_GRADE = MappingProxyType({
    grade: frozenset(characters)
    for grade, characters in _GRADE_CHARACTERS.items()
})
KANJI_GRADE = MappingProxyType({
    character: grade
    for grade, characters in _GRADE_CHARACTERS.items()
    for character in characters
})


def grade_for(character: str) -> int | None:
    """1文字の配当学年を返す。配当表外や1文字でない入力はNone。"""
    if not isinstance(character, str) or len(character) != 1:
        return None
    return KANJI_GRADE.get(character)


def _validate_grade(grade: int) -> None:
    if type(grade) is not int or not 1 <= grade <= 6:
        raise ValueError("grade must be an integer from 1 to 6")


def available_at_grade(character: str, grade: int) -> bool:
    """設定学年までに配当される漢字ならTrue。表外の文字はFalse。"""
    _validate_grade(grade)
    assigned_grade = grade_for(character)
    return assigned_grade is not None and assigned_grade <= grade


def kanji_through_grade(grade: int) -> frozenset[str]:
    """設定学年までの漢字を、変更できない集合として返す。"""
    _validate_grade(grade)
    return frozenset(
        character for character, assigned_grade in KANJI_GRADE.items()
        if assigned_grade <= grade
    )

