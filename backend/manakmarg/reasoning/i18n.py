"""English and Hindi answer templates. Identifiers (IS, S.O./G.S.R., recognition and OSL numbers, clauses, dates in
ISO form) are inserted unchanged and are never translated."""

MESSAGES: dict[str, dict[str, str]] = {
    # section titles
    "section.answer": {"en": "Answer", "hi": "उत्तर"},
    "section.standards": {"en": "Applicable Indian Standard", "hi": "लागू भारतीय मानक"},
    "section.why": {"en": "Why", "hi": "क्यों"},
    "section.orders": {"en": "Orders & notifications", "hi": "आदेश और अधिसूचनाएँ"},
    "section.other_listings": {"en": "Other matching listings", "hi": "अन्य मिलान सूचियाँ"},
    "section.district": {"en": "District coverage", "hi": "ज़िला कवरेज"},
    "section.ahcs": {"en": "Assaying & Hallmarking Centres", "hi": "परख और हॉलमार्किंग केंद्र"},
    "section.jewellers": {"en": "Registered jewellers", "hi": "पंजीकृत ज्वैलर्स"},
    "section.labs": {"en": "Laboratories", "hi": "प्रयोगशालाएँ"},
    "section.upcoming": {"en": "Upcoming QCOs", "hi": "आगामी QCO"},
    "section.process": {"en": "Official steps", "hi": "आधिकारिक चरण"},
    "section.faq": {"en": "From official BIS FAQs", "hi": "आधिकारिक BIS प्रश्नोत्तर से"},
    "section.documents": {"en": "From indexed official documents", "hi": "अनुक्रमित आधिकारिक दस्तावेज़ों से"},
    "section.tests": {"en": "Tests & inspection", "hi": "परीक्षण और निरीक्षण"},
    # product / compulsory status headlines
    "head.compulsory": {
        "en": "“{product}” is listed under {scheme} for compulsory BIS certification.",
        "hi": "“{product}” {scheme} के अंतर्गत अनिवार्य BIS प्रमाणन सूची में है।",
    },
    "head.upcoming": {
        "en": "A Quality Control Order covering “{product}” is notified; enforcement from {date} ({days} days from today).",
        "hi": "“{product}” पर लागू गुणवत्ता नियंत्रण आदेश अधिसूचित है; लागू तिथि {date} ({days} दिन शेष)।",
    },
    "head.enforcement_reached": {
        "en": "The enforcement date {date} listed for “{product}” has been reached — verify the current status with BIS.",
        "hi": "“{product}” के लिए सूचीबद्ध लागू तिथि {date} आ चुकी है — वर्तमान स्थिति BIS से सत्यापित करें।",
    },
    "head.denotified": {
        "en": "The BIS page marks “{product}” as de-notified from compulsory certification — verify before relying on it.",
        "hi": "BIS पृष्ठ पर “{product}” को अनिवार्य प्रमाणन से विअधिसूचित दर्शाया गया है — भरोसा करने से पहले पुष्टि करें।",
    },
    "head.verify": {
        "en": "The listing for “{product}” needs verification.",
        "hi": "“{product}” की सूची की पुष्टि आवश्यक है।",
    },
    "head.standard_no_listing": {
        "en": "{std_key} is a published Indian Standard, but no compulsory-certification listing for it was found in the indexed BIS pages.",
        "hi": "{std_key} एक प्रकाशित भारतीय मानक है, पर अनुक्रमित BIS पृष्ठों में इसकी कोई अनिवार्य प्रमाणन सूची नहीं मिली।",
    },
    "head.no_listing": {
        "en": "No compulsory-certification listing matched “{text}” in the indexed BIS pages.",
        "hi": "अनुक्रमित BIS पृष्ठों में “{text}” से मेल खाती कोई अनिवार्य प्रमाणन सूची नहीं मिली।",
    },
    "prefix.possible": {"en": "Possible match: ", "hi": "संभावित मिलान: "},
    "item.basis": {"en": "Status basis (quoted): {basis}", "hi": "स्थिति का आधार (उद्धरण): {basis}"},
    "item.matched": {"en": "Matched your words to the official product name “{product}” ({coverage}% of your product words).", "hi": "आपके शब्द आधिकारिक उत्पाद नाम “{product}” से मिलाए गए (आपके उत्पाद शब्दों का {coverage}%)."},
    "item.matched_standard": {"en": "Found through the standard you named ({ref}).", "hi": "आपके बताए मानक ({ref}) से मिला।"},
    "item.standard": {"en": "{std_key} — {title}", "hi": "{std_key} — {title}"},
    "item.standard_listed_as": {"en": "Listed on the BIS page as {ref}.", "hi": "BIS पृष्ठ पर {ref} के रूप में सूचीबद्ध।"},
    "item.order": {"en": "{kind}: {title}{number}{date}", "hi": "{kind}: {title}{number}{date}"},
    "item.listing": {"en": "{product} — {effect}", "hi": "{product} — {effect}"},
    "effect.COMPULSORY": {"en": "compulsory listing", "hi": "अनिवार्य सूची"},
    "effect.UPCOMING": {"en": "notified, not yet in force", "hi": "अधिसूचित, अभी लागू नहीं"},
    "effect.ENFORCEMENT_DATE_REACHED": {"en": "enforcement date reached", "hi": "लागू तिथि आ गई"},
    "effect.DENOTIFIED": {"en": "de-notified", "hi": "विअधिसूचित"},
    "effect.RESCINDED": {"en": "rescinded — verify", "hi": "निरस्त — पुष्टि करें"},
    "effect.NEEDS_VERIFICATION": {"en": "needs verification", "hi": "पुष्टि आवश्यक"},
    # hallmarking
    "head.hm_covered": {
        "en": "{district}, {state} is under mandatory hallmarking of gold jewellery (phase {phase}, {order}).",
        "hi": "{district}, {state} में सोने के आभूषणों की अनिवार्य हॉलमार्किंग लागू है (चरण {phase}, {order})।",
    },
    "head.hm_verify": {
        "en": "{district}, {state} appears in the official records but needs verification: {note}",
        "hi": "{district}, {state} आधिकारिक रिकॉर्ड में है पर पुष्टि आवश्यक है: {note}",
    },
    "head.hm_ambiguous": {
        "en": "“{district}” is a hallmarking district in more than one state ({states}). Please name the state.",
        "hi": "“{district}” एक से अधिक राज्यों ({states}) में हॉलमार्किंग ज़िला है। कृपया राज्य बताएँ।",
    },
    "head.hm_not_listed": {
        "en": "{district} was not found in the indexed list of mandatory hallmarking districts. Mandatory hallmarking applies only in notified districts — verify with BIS.",
        "hi": "{district} अनिवार्य हॉलमार्किंग ज़िलों की अनुक्रमित सूची में नहीं मिला। अनिवार्य हॉलमार्किंग केवल अधिसूचित ज़िलों में लागू है — BIS से पुष्टि करें।",
    },
    "head.hm_general": {
        "en": "Here is what the official BIS hallmarking records say.",
        "hi": "आधिकारिक BIS हॉलमार्किंग रिकॉर्ड के अनुसार जानकारी।",
    },
    "item.hm_gazette": {"en": "Gazette cross-check: {note}", "hi": "राजपत्र से मिलान: {note}"},
    "item.ahc_count": {
        "en": "{operative} operative AHC(s) found in {place}; {inactive} other centre(s) are suspended, cancelled or past validity and are not shown as operative.",
        "hi": "{place} में {operative} सक्रिय AHC मिले; {inactive} अन्य केंद्र निलंबित, रद्द या वैधता समाप्त हैं और सक्रिय नहीं दिखाए गए।",
    },
    "head.hm_state": {
        "en": "Mandatory hallmarking of gold jewellery applies district-wise: {count} district(s) of {state} are notified ({names}).",
        "hi": "सोने के आभूषणों की अनिवार्य हॉलमार्किंग ज़िलेवार लागू है: {state} के {count} ज़िले अधिसूचित हैं ({names})।",
    },
    "head.hm_state_none": {
        "en": "No district of {state} was found in the indexed list of mandatory hallmarking districts — verify with BIS.",
        "hi": "अनिवार्य हॉलमार्किंग ज़िलों की अनुक्रमित सूची में {state} का कोई ज़िला नहीं मिला — BIS से पुष्टि करें।",
    },
    "item.ahc": {"en": "{name} ({recognition_no}) — valid until {validity}", "hi": "{name} ({recognition_no}) — वैधता {validity} तक"},
    "item.ahc_status": {"en": "{name} ({recognition_no}) — {status}: {reason}", "hi": "{name} ({recognition_no}) — {status}: {reason}"},
    "item.jewellers": {
        "en": "Registered jewellers are listed only in the official Manakonline report, which requires a CAPTCHA; this prototype does not collect it.",
        "hi": "पंजीकृत ज्वैलर्स केवल आधिकारिक मानकऑनलाइन रिपोर्ट में हैं, जिसके लिए CAPTCHA आवश्यक है; यह प्रोटोटाइप उसे एकत्र नहीं करता।",
    },
    # labs
    "head.labs": {
        "en": "LIMS lists {count} laboratory scope row(s) for {refs}{place}.",
        "hi": "LIMS में {refs}{place} के लिए {count} प्रयोगशाला दायरा पंक्तियाँ सूचीबद्ध हैं।",
    },
    "head.labs_not_indexed": {
        "en": "Laboratory scope for {refs} is not indexed in this prototype — use the official LIMS search.",
        "hi": "{refs} का प्रयोगशाला दायरा इस प्रोटोटाइप में अनुक्रमित नहीं है — आधिकारिक LIMS खोज का उपयोग करें।",
    },
    "head.labs_none": {"en": "LIMS lists no laboratory for {refs}.", "hi": "LIMS में {refs} के लिए कोई प्रयोगशाला सूचीबद्ध नहीं है।"},
    "head.labs_need_standard": {
        "en": "Name the Indian Standard (for example IS 2062) or the product to find laboratories.",
        "hi": "प्रयोगशालाएँ खोजने के लिए भारतीय मानक (जैसे IS 2062) या उत्पाद बताएँ।",
    },
    "item.lab": {
        "en": "{name} — {place} · {ref} · {status}{charges}",
        "hi": "{name} — {place} · {ref} · {status}{charges}",
    },
    "item.labs_fallback": {"en": "No laboratory matched the location; laboratories elsewhere are shown.", "hi": "स्थान से कोई प्रयोगशाला मेल नहीं खाई; अन्य स्थानों की प्रयोगशालाएँ दिखाई गई हैं।"},
    # upcoming, process, general
    "head.upcoming_list": {
        "en": "{count} upcoming QCO listing(s) are notified with a future enforcement date (checked on {today}).",
        "hi": "{count} आगामी QCO सूचियाँ भविष्य की लागू तिथि के साथ अधिसूचित हैं ({today} को जाँचा गया)।",
    },
    "item.upcoming": {"en": "{product} ({refs}) — enforcement {date}, {days} days", "hi": "{product} ({refs}) — लागू {date}, {days} दिन"},
    "head.process": {
        "en": "Official BIS steps to apply for a product certification licence.",
        "hi": "उत्पाद प्रमाणन लाइसेंस के लिए आवेदन के आधिकारिक BIS चरण।",
    },
    "item.step": {"en": "Step {label}: {text}", "hi": "चरण {label}: {text}"},
    "head.faq": {"en": "Here is what official BIS sources say.", "hi": "आधिकारिक BIS स्रोतों के अनुसार जानकारी।"},
    "head.nothing": {
        "en": "I could not find an official answer in the indexed data. Try naming the product, an IS number or a district.",
        "hi": "अनुक्रमित डेटा में आधिकारिक उत्तर नहीं मिला। उत्पाद, IS संख्या या ज़िला बताकर देखें।",
    },
    "head.gap": {
        "en": "Use Gap Analysis to compare your datasheet or test report with requirements from a document you legitimately hold.",
        "hi": "अपनी डेटाशीट या परीक्षण रिपोर्ट की तुलना वैध रूप से उपलब्ध दस्तावेज़ की आवश्यकताओं से करने के लिए गैप विश्लेषण का उपयोग करें।",
    },
    "item.faq": {"en": "{question} — {answer}", "hi": "{question} — {answer}"},
    "item.sit": {"en": "{requirement} (clause {clause}): {frequency}", "hi": "{requirement} (खंड {clause}): {frequency}"},
    # next actions and links
    "action.journey": {"en": "Open the full compliance journey for this product.", "hi": "इस उत्पाद की पूरी अनुपालन यात्रा खोलें।"},
    "action.confirm": {"en": "Confirm that the listed product is yours.", "hi": "पुष्टि करें कि सूचीबद्ध उत्पाद आपका है।"},
    "action.verify": {"en": "Verify the status on the official BIS page.", "hi": "आधिकारिक BIS पृष्ठ पर स्थिति सत्यापित करें।"},
    "action.labs": {"en": "Check laboratories recognised for the standard.", "hi": "मानक के लिए मान्यता प्राप्त प्रयोगशालाएँ देखें।"},
    "action.apply": {"en": "Apply online on Manakonline after meeting the requirements.", "hi": "आवश्यकताएँ पूरी करने के बाद मानकऑनलाइन पर आवेदन करें।"},
    "action.ahcs": {"en": "Visit an operative AHC listed above for hallmarking.", "hi": "हॉलमार्किंग के लिए ऊपर सूचीबद्ध किसी सक्रिय AHC से संपर्क करें।"},
    "action.lims": {"en": "Search laboratories on the official LIMS portal.", "hi": "आधिकारिक LIMS पोर्टल पर प्रयोगशालाएँ खोजें।"},
    "link.journey": {"en": "Compliance journey", "hi": "अनुपालन यात्रा"},
    "link.labs": {"en": "Testing & labs", "hi": "परीक्षण और प्रयोगशालाएँ"},
    "link.hallmarking": {"en": "Hallmarking", "hi": "हॉलमार्किंग"},
    "link.upcoming": {"en": "Upcoming QCOs", "hi": "आगामी QCO"},
    "link.gap": {"en": "Gap analysis", "hi": "गैप विश्लेषण"},
    "link.standard": {"en": "Standard details", "hi": "मानक विवरण"},
    # follow-ups
    "follow.tests": {"en": "Which tests are required for {subject}?", "hi": "{subject} के लिए कौन से परीक्षण आवश्यक हैं?"},
    "follow.labs": {"en": "Labs for {subject}", "hi": "{subject} के लिए लैब"},
    "follow.apply": {"en": "How to apply for a BIS licence?", "hi": "BIS लाइसेंस के लिए आवेदन कैसे करें?"},
    "follow.ahcs": {"en": "Operative AHCs in {place}", "hi": "{place} में सक्रिय AHC"},
    "follow.huid": {"en": "What is HUID?", "hi": "HUID क्या है?"},
    "follow.upcoming": {"en": "Upcoming QCOs", "hi": "आगामी QCO"},
}


def say(key: str, lang: str, **params) -> str:
    template = MESSAGES[key].get(lang) or MESSAGES[key]["en"]
    return template.format(**{name: "" if value is None else value for name, value in params.items()})
