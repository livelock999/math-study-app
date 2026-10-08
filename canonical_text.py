"""学年表示用の、内容を確認した教材表記。

保存する問題・回答は一切変更しない。公開 API が返す辞書は「既知の表示文
全体 -> 正規表記」で、任意のひらがな文への検索置換には使わない。
読みは語全体で管理し、「はし」「あつい」などの同音異義語は収録しない。
"""

from functools import lru_cache
from hashlib import sha256
from itertools import permutations
import json
import re


# 表記と読みを対にしてレビューする。活用形も全文字が一致する形で登録。
# りんご・みかん・いすなど、教育漢字以外の字を含む語は元のままにする。
_MATERIAL_TERMS = (
    ("あかい", "赤い"), ("あおい", "青い"), ("あか", "赤"), ("あお", "青"),
    ("つみき", "積み木"), ("いぬ", "犬"), ("ぜんぶ", "全部"),
    ("のこり", "残り"), ("おおい", "多い"), ("こども", "子ども"),
    ("ひとり", "一人"), ("ひつよう", "必要"), ("かず", "数"),
    ("ぶんだけ", "分だけ"), ("ふえる", "増える"), ("なか", "中"),
    ("のこる", "残る"), ("くみにして", "組にして"),
    ("かんがえよう", "考えよう"), ("しき", "式"), ("ただしい", "正しい"),
    ("すすんで", "進んで"), ("もどって", "戻って"),
    ("かぞえよう", "数えよう"), ("かぞえて", "数えて"),
    ("ほん", "本"), ("はな", "花"), ("こうえん", "公園"),
    ("がっこう", "学校"), ("としょかん", "図書館"), ("せんせい", "先生"),
    ("ともだち", "友達"), ("いえ", "家"), ("みず", "水"), ("あめ", "雨"),
    ("ゆき", "雪"), ("あさ", "朝"), ("ゆうがた", "夕方"), ("よる", "夜"),
    ("うみ", "海"), ("おみせ", "お店"), ("みせ", "店"), ("にわ", "庭"),
    ("たいいくかん", "体育館"), ("かいもの", "買い物"),
    ("べんきょうします", "勉強します"), ("うんどうします", "運動します"),
    ("て", "手"), ("え", "絵"), ("かみ", "紙"), ("たね", "種"), ("め", "芽"),
    ("にちようび", "日曜日"), ("いちねんせい", "一年生"),
    ("きょう", "今日"), ("こたえ", "答え"),
    ("よみました", "読みました"), ("よみます", "読みます"),
    ("よんだ", "読んだ"), ("よむ", "読む"),
    ("たべました", "食べました"), ("たべます", "食べます"), ("たべた", "食べた"),
    ("とりのぞいて", "取り除いて"), ("のぞく", "除く"),
    ("あわせて", "合わせて"), ("あまる", "余る"),
)

_COMMON_TERMS = {
    "学習": "がくしゅう", "履歴": "りれき", "算数": "さんすう", "国語": "こくご",
    "問題": "もんだい", "答え": "こたえ", "解説": "かいせつ", "練習": "れんしゅう",
    "確認": "かくにん", "計算": "けいさん", "戻る": "もどる", "次へ": "つぎへ",
    "見る": "みる", "選ぶ": "えらぶ",
}

# 画面側はこの語単位で学年とふりがなを判定できる。
TERMS = {written: reading for reading, written in _MATERIAL_TERMS}
TERMS.update(_COMMON_TERMS)

DISPLAY_FIELDS = frozenset(("text", "question", "choices", "hint", "explanation",
                            "selected", "correct_answer"))


def protected_fields(subject, item):
    """文字の比較・穴埋めなど、文字自体を学ぶ問題を原文のまま保護する。"""
    if (isinstance(item, dict) and subject in ("japanese", "国語", "jp")
            and item.get("category") == "words"):
        # 解説にも正解の文字列が引用されるため、引用を含む全フィールドを保護。
        return set(DISPLAY_FIELDS)
    if (isinstance(item, dict) and subject in ("japanese", "国語", "jp")
            and item.get("category") == "particles"):
        return {"choices", "selected", "correct_answer"}
    return set()


# 日本語の任意の文章から単語を推測しない。既知教材の、分かち書きされた
# 語と助詞だけを承認する。語末の活用/接続語はここに明示したものに限定。
_BOUNDARY = r"[\s、。！？!?「」『』（）()○・→]"
_SUFFIX = r"(?:ですか|でしたか|です|でした|だよ|には|にも|から|より|だけ|ずつ|ため|は|が|を|に|で|と|も|へ|の|か|よ)?"
_PATTERN = re.compile(
    r"(?<![^\s、。！？!?「」『』（）()○・→])(" +
    "|".join(re.escape(reading) for reading, _ in sorted(
        _MATERIAL_TERMS, key=lambda pair: len(pair[0]), reverse=True)) +
    r")(?=" + _SUFFIX + r"(?:" + _BOUNDARY + r"|$))"
)
_WRITTEN = dict(_MATERIAL_TERMS)


def _reviewed_text(text):
    """非公開。照合済み教材の原文にのみ適用する。"""
    return _PATTERN.sub(lambda match: _WRITTEN[match.group(1)], text)


_JAPANESE_CONTENT_FIELDS = ("category", "problem_format", "text", "question", "choices",
                            "hint", "explanation", "answer", "version")


def _question_signature(item):
    material = {key: item.get(key) for key in _JAPANESE_CONTENT_FIELDS}
    return sha256(json.dumps(material, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


# この版で文脈を確認した教材だけを許可する。内容改訂・新規追加時は、本文を
# レビューしてから対応する署名を更新する（IDだけで変換を許可しない）。
_JAPANESE_SIGNATURES = {
    'jp_sentence_001': '87939c3da988cfd1de3e861ecde4978bad5e1cdd04cc111f9b4d99c789255085',
    'jp_sentence_002': '2cedc7343de65623ee7a959b20dc8e86ed02d6e60399439fed66e6170074440e',
    'jp_sentence_003': '8184e0a3e06b709f63b9c9caafbd73042360d6cff07b38b3f948d97607def7ce',
    'jp_sentence_004': '0a0639bb7a0968b0582494807935eab28d80c9a1d7d6ad6c0a1620f7b40c4ac5',
    'jp_sentence_005': '14c74f8752f02affb06190e495c3f4a9b13c93da5af26697172b0af6c36f24a2',
    'jp_sentence_006': 'db9375390793ad10bce3fea08c3c88049192827027d49d7ae183d014a5bc37b9',
    'jp_sentence_007': 'f30c6137a1633d5e3780d21da14e8562661d652129fffeb28bcbb02dbb28aaa3',
    'jp_sentence_008': '2909b94014f5cfd57cb03c8da1719768202e90b0937d7703cf42a655a596e38e',
    'jp_sentence_009': 'ee737981f9fd2f940ef456321bc1a103cdfd153f2fbbc573b9c297ef94f46103',
    'jp_sentence_010': '10b9b123314f46bde10d560d1383d07f0bacdee066bbe579b07bc1add345f6a1',
    'jp_sentence_011': '77483ac6afc808b51ce6a0cb9683b274f175d8dedfb565f6c4a798b07fa7813f',
    'jp_sentence_012': 'cf59b2b11ea062fdc371894cf4d5851424a17ec8c0719d60bb7dd4ca719805d8',
    'jp_information_001': '0f77fce7c265d47c2be489c34ee595e332a420bd1b4e173df30c4c80f1d52da6',
    'jp_information_002': '266b7571483e24993b36e459bd6cd2c54e15db7d88da0f8e22dc81ee281d541e',
    'jp_information_003': 'cc16414e8da9af6225885b72cfa902a7534ff3fe7ef0780b6d392b277117d00c',
    'jp_information_004': 'fd2cfbbd4835fe9d258f7927f377ab3a088deff92f604b29245709129821642b',
    'jp_information_005': 'df4ad3725ea8547faf2155f62773be43dff7c91968748c6a197e2ce5e3b75547',
    'jp_information_006': '74a92641a301ac9eadeda05cb5457ab7f2073351c5522855373504e4766e06a3',
    'jp_information_007': '8e0de0ce00cb7420eae26d2db4d662bec9a491243248499ee038f2977074dc25',
    'jp_information_008': '4dd8126baa588e1a2eff087faafb80894165bd24e09d686b7fbd9fab7dfe6458',
    'jp_information_009': '3edb3a5abb1b23a349bcbe94f4a3c9d30d16be7f8fa3286e7d79d50bd8ea63dc',
    'jp_information_010': '735a7819cf3998c62c62ee2906d91f1a06ac61be4d28e643ea896800e5955b48',
    'jp_information_011': 'f3f1112317df38982f1f4ff3fd7bcec569f2eb103e92bd6f9078a3e60b5ff7c7',
    'jp_information_012': '933ac64841683e11c3ff171912817c2b86a5587e0480fb5273f7193aa16e2503',
    'jp_information_013': 'b63be23ac3bf0b870b48eb1fc79b75411b7225e76d776d40628f0a81ed49322f',
    'jp_information_014': '9cb34f1a6fc6a70ca48912ae8a44d7ce84a408a9f57a279f3e7edc96f5a33107',
    'jp_information_015': '292207191d496eef13705ea41a5a037aa5d6c73ba8414ae8f27b75b47fb7d5b3',
    'jp_information_016': 'a005ed8c0d5f3f1a1594aeb9c7afc7981f571aa98cc0369d999473a7963568b9',
    'jp_information_017': '88cff85cb58904c49e08ac9789f5e4a1b4a0bea08a852ccf35a397221ef41d03',
    'jp_information_018': 'e2fd0692af6e049d5522747a732510be49e0f4b9713c1f56cdccd99605499695',
    'jp_sequence_001': '2d3c2af90233567f28ff71e528fddc8b3e0b8d936a2010c47ee8d039fb559e5f',
    'jp_sequence_002': 'abfef7c4ab94587dc0ed8b110ff8b119a4012d214c511512dac956fe12099e67',
    'jp_sequence_003': '46aa48f34b2459769789407f79503ad0180ebfcd713735e66e4d1178bd0aaeac',
    'jp_sequence_004': '6dea7d4fda2f29928f9022208f85acf90c408add97e151f306083e8061c21e39',
    'jp_sequence_005': '72fa97b062eea4b26fa5cf34e009d1b3ee192d13d64151041412b8d06832492a',
    'jp_sequence_006': '7e18d3e8d9fa007cd8f3bb70e34a245f37b79a4fa734c41786336bd336f8698c',
    'jp_sequence_007': 'afa26b986ba7bc6e2998c9dcb575f818fe2c831753aed122252c3d907b5a184d',
    'jp_sequence_008': '461febd71ac8cd17848e001dc2ebbe32134b6afcd7e6fef3bc44cbf2db7cab36',
    'jp_sequence_009': '6913ff994563fa12b536613f31ce089e9f9ff2b27c4cb1e6977cf2848a9e5f2b',
    'jp_sequence_010': 'e6025ad0f5e92827e1ab3c4498b256082866946d44c4a1551ea150d132c8d823',
    'jp_passage_001': '26b72cb7cd76d7d0d2b83e56148674ed1169d8fcfcbff0a6047072c26a1b91b1',
    'jp_passage_002': 'a0b323573b51d6955d5d937a6ca725328321b3562f179b1c2285fbce8821c249',
    'jp_passage_003': 'cfdbd220542974f489235b9e4e955c2d812c4c37b95e6560d14a47eb9c7ad22e',
    'jp_passage_004': '0cd72afcabb263c413efd8763bdf81684727b91b8da0cb30902abdb0bb71e8fc',
    'jp_passage_005': 'd1ec5ab8c7ad55633a555ddf85b00b52d74115b7b87f9d52535359393dbf14df',
    'jp_passage_006': '87b8893c7d9da2d8a0f62bab0a9882e4b066d3cab716875a32b29ccedf9b63ad',
    'jp_passage_007': '785b5a9e85a6990833e29eeca352d5c96cc2d0588ca6c519372b4af76f62591c',
    'jp_passage_008': '91204a55d4ea478f60c017bab05478244962cfdccdf32e2d68a80bbe3dd84dc9',
    'jp_passage_009': '6dc73f6a92604ea3370aeca4adb194cab7adb6c4bfc8e3a7c85a0405f8560497',
    'jp_passage_010': 'aa9d9208ae79cfb9f48928aee7a45f3fafd868a7ee9d8bf09760eac3af2eaa82',
    'jp_passage_011': '2f04d7e3d16191b9bee86a33c85797ac9eb6252c30b9b5db5a59ccc12e62680e',
    'jp_passage_012': 'c8c81bffaa6616f1965cf1f6e71f0b1871f05d3ad45b0932f52dcd71a5d0e1a7',
    'jp_passage_013': 'eaa117190aa26595aaa717cb5768cadcea092be0dd427e5012bcd02e387d84f9',
    'jp_passage_014': '1529589d874c0c20045e53bc632e96b9a9edab1eefaaadfd494c99321a29c759',
    'jp_passage_015': 'e16fb1846f057c7782677a2323b6ca8216c2d59f851320a66fde5d620dc589ec',
    'jp_passage_016': '25753409004997953d1c368968a6b3d1d349eec86c199559f941e2b779eef50b',
    'jp_passage_017': '986850d9de03e209dca437d5d342c49f0cfe71fd1525f391c9d93527706cc568',
    'jp_passage_018': '3f2e83735987e29b706adbbf85cbccb938a51466ad2c3b9f35e8005f0d06b286',
    'jp_blank_001': '5949e8ea855e979312259ef69a638354c39e5adc5c5ed4b037956545423334f9',
    'jp_blank_002': 'ce56d840227984098d0c9b0b77ce5a70b6d5f90705d3148cd3f697018e7529fd',
    'jp_blank_003': '70669e678a7bd933756c43056937801a908e239b0ee3aaea544d38c147989512',
    'jp_blank_004': '5c651bbb8994ef401e26eb30f31e3a3ec7579474d482db75e44a71a6444a3977',
    'jp_blank_005': '70139f6ff26b85e4d749a9f0b8efbf2d647248ca32b8897e8a7894c0c8ae88c0',
    'jp_blank_006': '48f9436b869fc4b96091ab146a0eccc9f9e95a658b3c093e852841e13491f310',
    'jp_blank_007': 'fdfe1daaf5cecce4730facb41c80e6fccf5f531a013471ab5b41f730e28b8ccc',
    'jp_blank_008': '5c09b5fd54adb4f449d13e08deaf2050ec12c794cb74c9f26abac6ae1e7de8f2',
    'jp_blank_009': 'a205cdf44430aecd306e90315967d220036a8b4d5dad637f787f0088c18d36fc',
    'jp_blank_010': '7c7d22c4dff7db14ee3dea46d889ebdb7ff522277520f2e1b23e27d6284132cb',
    'jp_particles_001': '6b96f9f3a7258b98f02c9bab50f39b7d5d387df91bc48338dbf72d536c0ef0c0',
    'jp_particles_002': '262927eebda7a4d976f62b8624a22545a56e20b401c2889ae146c3db89b5ffcb',
    'jp_particles_003': 'daba3d829e543b060d6f06676e875d6703861c3ea6b6864bb8c5ba536c110f40',
    'jp_particles_004': '5a108dac58beccbd124281b748e4ec0bd741673abbad57c6f76b140eb0919532',
    'jp_particles_005': 'aa0271e4b2f73b899fc3bd8b543323245b455f5301bae1176eef045c4b1065c3',
    'jp_particles_006': '28dbd135aa2bc1823a7e2659ccb82cd9ef8332e053ea8e05cb9941dadab71d24',
    'jp_particles_007': 'c3cb2ef3e4bd2c4d7c0462bd109690900a4838eb749f30070b28a00b75ca2322',
    'jp_particles_008': '36e57cb70fec1b34b8153cbfe6f60946735db51d968a394ccea33858fc5f7302',
    'jp_particles_009': '49ef62320bbf797ed707bb6eb6fdb4b9c17e09dc6778f24e9b51c926d33534a4',
    'jp_particles_010': 'be451eaf80e37c5351457573c42ab55ccc2296caa55c19f99da9899cbc8f1e8b',
    'jp_particles_011': '149911cd7606f6d38bcc65ce05003ee551e5fa8fb1a5edd04282237310a06b72',
    'jp_particles_012': 'a6c1a276a02891ea6435bae19d81c878f82d29f07c0baa282601d82435a47990',
    'jp_particles_013': 'ea71dbc2eb4c2bba79cfc04ed0cd9b25db5418c2a236f7aa8a849015b4605409',
    'jp_particles_014': '25e4030ca8b8bc8fd793ffb61b58a3b7c5bf16198332fb61db3ceed063e7c8ad',
    'jp_particles_015': '7d679bd6bfb35215464d3a4399e4bd477d599e53f916e1f1358ef8252d784f77',
    'jp_particles_016': 'd9fc421c8c8818bf931df2c0b4a61713d1f7a9237028636dc4b76263a15dbcbb',
    'jp_particles_017': '2444e1d9d42bf65053fc8b77b848810e9fa234d0e6500e3ba8e01dd5be404b40',
    'jp_particles_018': 'c7b9b40c54829c40adbab0ab6f3c46a4aa1e9f23ee4bf2f73ea1218114c13318',
    'jp_particles_019': '87274e14253921f3339a2429f36b9c1e2c9bef0b42d52d2f2b35e2033964d8c4',
    'jp_particles_020': 'f3d227f0d3c63085ddca8db8104ba7d31f590b22e2f1124e004991d772f4a00e',
    'jp_particles_021': 'e9000df0fc92fc6d3349c17342ea8eec71ed68bb1bdcea4963a99175b1e8ff84',
    'jp_particles_022': '56368606a494e7519d848866d7e0c1470a3074516f8d6d01fec63ddcb14f765d',
    'jp_particles_023': 'fa07781ed3700e66a9baac226d5e6dcc701c2a8cc6bdb8038725bc31da02016b',
    'jp_particles_024': '06c68f4293337e2825d2d44e7dc2259b8c1c7cbe55dc4af2dab714edd9dc6254',
    'jp_particles_025': 'ea71dbc2eb4c2bba79cfc04ed0cd9b25db5418c2a236f7aa8a849015b4605409',
    'jp_particles_026': '25e4030ca8b8bc8fd793ffb61b58a3b7c5bf16198332fb61db3ceed063e7c8ad',
    'jp_particles_027': '7d679bd6bfb35215464d3a4399e4bd477d599e53f916e1f1358ef8252d784f77',
    'jp_particles_028': 'd9fc421c8c8818bf931df2c0b4a61713d1f7a9237028636dc4b76263a15dbcbb',
    'jp_particles_029': '70e30671e6c4a0c64a07ff3e10100bcdbd5e879da7a55bbf1f998db820cda8e7',
    'jp_particles_030': 'c7b9b40c54829c40adbab0ab6f3c46a4aa1e9f23ee4bf2f73ea1218114c13318',
    'jp_particles_031': '98459df0c3c3701ad3e87df91bbc4dddc1cfde989c3c30fd1a1cef2404cf9508',
    'jp_particles_032': '1516b6fd3781ca016beb4bab6abfa91287d2435b2b18177695a45bf3786abd78',
    'jp_particles_033': 'e9000df0fc92fc6d3349c17342ea8eec71ed68bb1bdcea4963a99175b1e8ff84',
    'jp_particles_034': '97e68d9a98db608751b1107572c8df9aafd4848445a1a8f000c06024ee717a3f',
    'jp_particles_035': 'eef9f8ec02985dfcec572275f1e844c546bc8c9a4d2fc2ed48a4528d867d0e5a',
    'jp_particles_036': '06c68f4293337e2825d2d44e7dc2259b8c1c7cbe55dc4af2dab714edd9dc6254',
    'jp_particles_037': 'f30b64c6a52966bc58658930f13a2d627a03438b3c4b62e077b395cefb698e6a',
    'jp_particles_038': '0875f88613675b771fe695e7b3f0445663c70d74f188bdd5d552e2c724a56f0b',
    'jp_particles_039': '7f5d7099ed755772aa0375eaf2685930ff1fb561fc67687754e4b172032fd694',
    'jp_particles_040': 'd7d8cecd4e4c292745beb0a0682421a1ed4a9ff4e3b4f61681ae06fa86562264',
    'jp_reading_v1_001': 'f2d248a9e89f8b2f4e2e1baee0e0bc6fc1eac3da194c41170cddb9921845e88c',
    'jp_reading_v1_002': 'f2f250f0be64425726b986b70520cc6961256d4a1f5aa61a896de905affc318a',
    'jp_reading_v1_003': 'b7cb7b6462905f36c4a4e9b7f328333729bc83a1cddca27a01819e6b1216d925',
    'jp_reading_v1_004': '4222ad1add68af3089af68446347f7b979dc4cffc2dfbcb44d4e3210ade6b653',
    'jp_reading_v1_005': 'f68dceed28cda6ca813d45a88fee9615879082ca73fbcda5527f4633ca44ace8',
    'jp_reading_v1_006': '7786470101e2b68c083664e059d20db96a4efb364251d28bda525b7d1194270f',
    'jp_reading_v1_007': '2d70a42c2f2a65764a6a41003fa46ecc653413834c3a4a8d045d89a1c385ff55',
    'jp_reading_v1_008': '4cc41b4ebf073e15da67e7b606fe85fb6a7b657506a74a79b0ca0253f0e6d63a',
    'jp_reading_v1_009': 'ddc76ef273a2eb2d0a5d14555f9010cbcf9c5ba5edc7c4d9e7dae13ea8103275',
    'jp_reading_v1_010': '168b32940f4bba19bd76ef06216a3e3c9911cefe0e7c71c0d5883f9169fa3896',
    'jp_reading_v1_011': 'b88e7182bfeb3d2a27ae9cd38ae2ed7ad3595ea8ff3e601f85bc7a5ea3f8eec0',
    'jp_reading_v1_012': 'babc6ea5cb120abd2ec7d6df25e8dc4c0d3a29a7101d314b9c3b8d9e14d09124',
    'jp_reading_v1_013': '0b619e814a043d7dc08336376f500a0d1683fa05b6a63f7a901f14a97c6dc01d',
    'jp_reading_v1_014': '1fc03adb6ed25d8ac07250e336eb40f97a636a2fbad9bd8289b9c892c9b89426',
    'jp_reading_v1_015': '883d64c5830b1bce6bc386bec263d127ba933ff7dac3088bf6bc0d35a1548cd2',
    'jp_reading_v1_016': 'deb1a7bb470b0e4ebfd9e18c8d06f84aa01cbc8330b418a5a09b1269d1e4e9b4',
}


@lru_cache(maxsize=1)
def _japanese_catalog():
    from japanese_questions import QUESTIONS
    return {q["question_id"]: q for q in QUESTIONS
            if _JAPANESE_SIGNATURES.get(q["question_id"]) == _question_signature(q)}


def _known_japanese_item(item):
    known = _japanese_catalog().get(item.get("question_id"))
    if (known is None or _JAPANESE_SIGNATURES.get(known["question_id"])
            != _question_signature(known)):
        return None
    # 同じIDでも教材を改訂した場合は、自動で古い表記ルールを流用しない。
    for field in _JAPANESE_CONTENT_FIELDS:
        if item.get(field) != known.get(field):
            return None
    return known


_MATH_STORIES = {
    "increase": "りんごが {left}こ あります。{right}こ もらいました。いま なんこ ありますか。",
    "decrease": "りんごが {left}こ あります。{right}こ たべました。のこりは なんこ ですか。",
    "combine": "あかい つみきが {left}こ、あおい つみきが {right}こ あります。あわせて なんこ ですか。",
    "separate": "いぬと ねこが ぜんぶで {left}ひき います。いぬは {right}ひき です。ねこは なんびき ですか。",
    "compare": "りんごが {left}こ、みかんが {right}こ あります。りんごは みかんより なんこ おおいですか。",
    "difference": "こどもが {left}にん います。いすは {right}こ あります。ひとりに いすが 1こ ひつようです。いすは あと なんこ いりますか。",
    "increase_start": "りんごを {right}こ もらったら、{left}こに なりました。はじめに りんごは なんこ ありましたか。",
    "increase_change": "りんごが {right}こ ありました。いくつか もらって、{left}こに なりました。なんこ もらいましたか。",
    "decrease_start": "りんごを {right}こ たべたら、{left}こ のこりました。はじめに りんごは なんこ ありましたか。",
    "decrease_change": "りんごが {left}こ ありました。いくつか たべて、{right}こ のこりました。なんこ たべましたか。",
}
_MATH_HINTS = {
    "increase": "はじめの かずから、もらった ぶんだけ ふえるよ。",
    "decrease": "はじめに あった ものから、たべた ものを とりのぞいて みよう。",
    "combine": "あかと あおを ひとつに まとめて かぞえて みよう。",
    "separate": "ぜんぶの なかから いぬを のぞくと、ねこが のこるよ。",
    "compare": "りんごと みかんを 1こずつ くみにして、あまる かずを かんがえよう。",
    "difference": "こどもと いすを 1つずつ くみにして、いすの ない こどもの かずを かんがえよう。",
    "increase_start": "いまの かずから、もらった ぶんを もどすと、はじめの かずに なるよ。",
    "increase_change": "はじめの かずと いまの かずを くらべると、ふえた ぶんが わかるよ。",
    "decrease_start": "のこった ぶんと たべた ぶんを あわせると、はじめの かずに なるよ。",
    "decrease_change": "はじめの かずと のこった かずを くらべると、たべた ぶんが わかるよ。",
    "addition_plain": "はじめの かずから、もう ひとつの かずだけ すすんで かぞえよう。",
    "addition_carry": "10の まとまりを つくって、のこりの かずを かんがえよう。",
    "subtraction_plain": "はじめの かずから、ひく かずだけ もどって かぞえよう。",
    "subtraction_borrowing": "10の まとまりを ばらして、ひく かずを とりのぞこう。",
}


_THREE_WORD_STORIES = {
    "increase_twice": "りんごが {a}こ あります。{b}こ もらいました。そのあと、また {c}こ もらいました。いま なんこ ありますか。",
    "decrease_twice": "りんごが {a}こ あります。{b}こ たべました。そのあと、また {c}こ たべました。のこりは なんこ ですか。",
    "increase_then_decrease": "りんごが {a}こ あります。{b}こ もらいました。そのあと、{c}こ たべました。のこりは なんこ ですか。",
    "decrease_then_increase": "りんごが {a}こ あります。{b}こ たべました。そのあと、{c}こ もらいました。いま なんこ ありますか。",
}


def _known_math_item(item):
    from learning import make_problem
    from words import make_word_problem
    try:
        operation = item["operation"]
        limit, left, right = (item[key] for key in ("number_range", "left_operand", "right_operand"))
        if operation not in ("addition", "subtraction") or limit not in (10, 20):
            return None
        if (type(left) is not int or type(right) is not int or not 0 <= left <= limit
                or not 0 <= right <= limit
                or (left + right > limit if operation == "addition" else right > left)):
            return None
        if item.get("problem_format") == "word_problem":
            known = make_word_problem(item["story_type"], limit, left, right)
            approved = _MATH_STORIES.get(item["story_type"])
            if approved is None or item.get("question_text") != approved.format(left=left, right=right):
                return None
        elif item.get("problem_format") == "calculation":
            known = make_problem(operation, limit, left, right)
        elif item.get("problem_format") == "fill_blank":
            from fill_blank import make_fill_problem
            known = make_fill_problem(operation, limit, left, right, item.get("blank_position"))
        elif item.get("problem_format") == "three_numbers":
            from three_numbers import make_three_problem
            known = make_three_problem(operation, item.get("second_operation"), limit,
                                       left, right, item.get("third_operand"))
        elif item.get("problem_format") == "three_word_problem":
            from three_word import make_three_word_problem
            known = make_three_word_problem(item.get("story_type"), limit, left, right, item.get("third_operand"))
            approved = _THREE_WORD_STORIES.get(item.get("story_type"))
            if approved is None or item.get("question_text") != approved.format(a=left, b=right, c=item.get("third_operand")):
                return None
        else:
            return None
        for field in ("problem_id", "question_text", "correct_answer", "operation",
                      "carry", "borrowing", "story_type", "unknown_type", "third_operand", "second_operation"):
            if item.get(field) != known.get(field):
                return None
        return known
    except (KeyError, TypeError, ValueError):
        return None


def _mapping(values):
    return {value: canonical for value in values
            if (canonical := _reviewed_text(value)) != value}


def canonical_fields(subject, item):
    """表示フィールドごとの {原文全体: 正規表記} を返す。

    例: result['text'].get(actual_text, actual_text)。文字列全体で照合し、
    部分文字列置換はしない。未知問題や原文改訂は空辞書にして誤変換を防ぐ。
    """
    if not isinstance(item, dict):
        return {}
    if subject in ("japanese", "国語", "jp"):
        protected = protected_fields(subject, item)
        if protected == DISPLAY_FIELDS:
            return {field: {} for field in DISPLAY_FIELDS}
        known = _known_japanese_item(item)
        if known is None:
            return {}
        fields = {field: _mapping([known[field]])
                  for field in ("text", "question", "hint", "explanation")}
        choices = known["choices"]
        fields["choices"] = _mapping(choices)
        # 並べ替えの途中や誤答も原文の選択肢を組み合わせた表示として扱う。
        answers = list(choices)
        if known["problem_format"] == "ordering":
            for count in range(2, len(choices) + 1):
                answers.extend(" → ".join(order) for order in permutations(choices, count))
        fields["selected"] = _mapping(answers)
        fields["correct_answer"] = dict(fields["selected"])
        for field in protected:
            fields[field] = {}
        return fields
    if subject in ("math", "算数"):
        known = _known_math_item(item)
        if known is None:
            return {}
        from words import guidance
        if known["problem_format"] in ("fill_blank", "three_numbers", "three_word_problem"):
            # 新教材の文はひらがなで用意する。既存計算用の結果・解説テンプレートは適用しない。
            question = _mapping([known["question_text"]])
            return {"question": question, "question_text": dict(question),
                    "hint_text": {}, "explanation_text": {}}
        if known["problem_format"] == "word_problem":
            hint_key = known["story_type"]
        elif known["operation"] == "addition":
            hint_key = "addition_carry" if known["carry"] else "addition_plain"
        else:
            hint_key = "subtraction_borrowing" if known["borrowing"] else "subtraction_plain"
        expected_hint = _MATH_HINTS[hint_key]
        sign = "+" if known["operation"] == "addition" else "−"
        expected_explanation = (expected_hint + f" ただしい しきは {known['left_operand']} "
                                f"{sign} {known['right_operand']} = {known['correct_answer']} だよ。")
        actual_hint, actual_explanation = guidance(known), guidance(known, reveal=True)
        question = _mapping([known["question_text"]])
        fields = {"question": question, "question_text": dict(question)}
        # 未承認の文はキーごと省く。空辞書は「承認済みだが置換不要」を表す。
        # 表示側が改訂後の原文を語辞書で処理してしまうことを防ぐ。
        if actual_hint == expected_hint:
            fields["hint_text"] = _mapping([actual_hint])
        if actual_explanation == expected_explanation:
            fields["explanation_text"] = _mapping([actual_explanation])
        return fields
    return {}


def get_terms(subject, item, field=None):
    """canonical_fields の辞書を取り出す便宜 API（キーは元の全文）。"""
    fields = canonical_fields(subject, item)
    if field is not None:
        return dict(fields.get(field, {}))
    return {original: written for mapping in fields.values()
            for original, written in mapping.items()}
