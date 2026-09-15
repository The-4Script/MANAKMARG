// Bilingual wording for codes returned by the reasoning services (steps, caveats, notes, next actions).
import type { Lang } from "./strings";

type Text = { en: string; hi: string };

export const STEP_TITLES: Record<string, Text> = {
  product: { en: "Product understanding", hi: "उत्पाद की पहचान" },
  standards: { en: "Applicable Indian Standard", hi: "लागू भारतीय मानक" },
  compulsory_status: { en: "Compulsory status & QCOs", hi: "अनिवार्यता की स्थिति और QCO" },
  scheme: { en: "Certification scheme", hi: "प्रमाणन योजना" },
  product_manual: { en: "Product Manual", hi: "उत्पाद मैनुअल" },
  tests: { en: "Tests & inspection", hi: "परीक्षण और निरीक्षण" },
  labs: { en: "Laboratories", hi: "प्रयोगशालाएँ" },
  application: { en: "Apply for the licence", hi: "लाइसेंस के लिए आवेदन" },
};

export const CAVEATS: Record<string, Text> = {
  listing_snapshot: {
    en: "BIS listings are snapshots with retrieval dates; verify the current legal position on the official BIS page and the latest Gazette.",
    hi: "BIS सूचियाँ प्राप्ति तिथि वाले स्नैपशॉट हैं; वर्तमान कानूनी स्थिति की पुष्टि आधिकारिक BIS पृष्ठ और नवीनतम राजपत्र से करें।",
  },
  absence_not_proof: {
    en: "No compulsory-certification listing was found in the indexed BIS pages. BIS certification is voluntary unless a QCO covers the product — this is not proof that none applies.",
    hi: "अनुक्रमित BIS पृष्ठों में कोई अनिवार्य प्रमाणन सूची नहीं मिली। जब तक कोई QCO उत्पाद को कवर न करे, BIS प्रमाणन स्वैच्छिक है — यह इस बात का प्रमाण नहीं है कि कोई आदेश लागू नहीं है।",
  },
  confirm_product: {
    en: "The match is based on your product description. Confirm that the listed product is yours before relying on it.",
    hi: "मिलान आपके उत्पाद विवरण पर आधारित है। भरोसा करने से पहले पुष्टि करें कि सूचीबद्ध उत्पाद आपका ही है।",
  },
  status_needs_verification: {
    en: "The matching listing is de-notified, rescinded, marked for verification, or its enforcement date has passed. Verify with BIS.",
    hi: "मिलान सूची विअधिसूचित, निरस्त या पुष्टि हेतु चिह्नित है, या उसकी लागू तिथि बीत चुकी है। BIS से पुष्टि करें।",
  },
  version_not_in_published_list: {
    en: "A referenced version is not in the published-standards list used here; the listed versions are shown instead.",
    hi: "संदर्भित संस्करण यहाँ उपयोग की गई प्रकाशित मानक सूची में नहीं है; सूचीबद्ध संस्करण दिखाए गए हैं।",
  },
  listed_and_upcoming: {
    en: "This product appears on a scheme page and on the upcoming-QCO page with a future enforcement date. The upcoming listing is shown first; verify when certification becomes mandatory.",
    hi: "यह उत्पाद योजना पृष्ठ पर और भविष्य की लागू तिथि के साथ आगामी QCO पृष्ठ पर भी है। आगामी सूची पहले दिखाई गई है; प्रमाणन कब अनिवार्य होगा, इसकी पुष्टि करें।",
  },
  matched_via_synonym: {
    en: "Some matches used a curated synonym (a search aid, not evidence).",
    hi: "कुछ मिलान संकलित पर्यायवाची (खोज सहायता, साक्ष्य नहीं) से हुए।",
  },
  possible_typo: {
    en: "The IS number looks mistyped (letters mixed with digits). No standard was looked up; check the number on the BIS standards portal.",
    hi: "IS संख्या में टाइपिंग त्रुटि लगती है (अंकों के साथ अक्षर)। कोई मानक नहीं खोजा गया; BIS मानक पोर्टल पर संख्या जाँचें।",
  },
  hsn_not_definitive: {
    en: "HSN codes are a classification lookup from the supplied HSN master, not a GST, customs or BIS determination. Verify before use.",
    hi: "HSN कोड दिए गए HSN मास्टर से वर्गीकरण खोज हैं, GST, सीमा शुल्क या BIS का निर्णय नहीं। उपयोग से पहले पुष्टि करें।",
  },
  location_not_recognised: {
    en: "The place you named is not in the indexed district, state or laboratory location lists, so it was not used as a filter.",
    hi: "आपका बताया स्थान अनुक्रमित ज़िला, राज्य या प्रयोगशाला स्थान सूचियों में नहीं है, इसलिए इसे फ़िल्टर के रूप में उपयोग नहीं किया गया।",
  },
};

export const NOTES: Record<string, Text> = {
  absence_not_proof: CAVEATS.absence_not_proof,
  no_standard_identified: { en: "No Indian Standard could be identified from the official records.", hi: "आधिकारिक रिकॉर्ड से कोई भारतीय मानक पहचाना नहीं जा सका।" },
  no_listing: { en: "No compulsory-certification listing matched.", hi: "कोई अनिवार्य प्रमाणन सूची मेल नहीं खाई।" },
  scheme_not_stated_on_upcoming_page: {
    en: "The upcoming-QCO page does not state the certification scheme; check the QCO document.",
    hi: "आगामी QCO पृष्ठ पर प्रमाणन योजना नहीं बताई गई है; QCO दस्तावेज़ देखें।",
  },
  no_manual_listed: { en: "BIS lists no Product Manual for this standard.", hi: "BIS इस मानक के लिए कोई उत्पाद मैनुअल सूचीबद्ध नहीं करता।" },
  manual_not_parsed: {
    en: "The Product Manual is listed but its text is not indexed here; open the official PDF.",
    hi: "उत्पाद मैनुअल सूचीबद्ध है पर उसका पाठ यहाँ अनुक्रमित नहीं है; आधिकारिक PDF खोलें।",
  },
  manual_access_denied: {
    en: "The official Product Manual PDF refused automated access (HTTP 403); it was not retried.",
    hi: "आधिकारिक उत्पाद मैनुअल PDF ने स्वचालित पहुँच अस्वीकार की (HTTP 403); दोबारा प्रयास नहीं किया गया।",
  },
  tests_from_lab_scope_only: {
    en: "No parsed Product Manual — these are tests a LIMS-listed lab is recognised for, not the scheme of inspection.",
    hi: "पार्स किया उत्पाद मैनुअल नहीं — ये LIMS-सूचीबद्ध लैब के मान्यता प्राप्त परीक्षण हैं, निरीक्षण योजना नहीं।",
  },
  no_test_information: { en: "No test information is available in the indexed data.", hi: "अनुक्रमित डेटा में परीक्षण जानकारी उपलब्ध नहीं है।" },
  scope_not_indexed: {
    en: "Lab scope for this standard is not indexed; use the official LIMS search.",
    hi: "इस मानक का लैब दायरा अनुक्रमित नहीं है; आधिकारिक LIMS खोज का उपयोग करें।",
  },
  no_scope_rows: { en: "LIMS lists no laboratory for this standard.", hi: "LIMS इस मानक के लिए कोई प्रयोगशाला सूचीबद्ध नहीं करता।" },
  no_labs_found: { en: "No laboratories found.", hi: "कोई प्रयोगशाला नहीं मिली।" },
  location_fallback: { en: "No labs in the chosen location — showing labs elsewhere.", hi: "चुने गए स्थान में लैब नहीं — अन्य स्थानों की लैब दिखाई जा रही हैं।" },
  steps_describe_scheme_i_licence: {
    en: "These official steps describe a Scheme I licence; follow the scheme page for other schemes.",
    hi: "ये आधिकारिक चरण योजना I लाइसेंस के हैं; अन्य योजनाओं के लिए योजना पृष्ठ देखें।",
  },
  no_process_steps: { en: "Official application steps are not indexed.", hi: "आधिकारिक आवेदन चरण अनुक्रमित नहीं हैं।" },
  gazette_only: {
    en: "Listed in the Gazette district annex but not in BIS's phase-wise list — verify with BIS.",
    hi: "राजपत्र ज़िला अनुसूची में सूचीबद्ध पर BIS की चरणवार सूची में नहीं — BIS से पुष्टि करें।",
  },
  gazette_not_checked: { en: "Gazette cross-check not available.", hi: "राजपत्र से मिलान उपलब्ध नहीं।" },
};

export const ACTIONS: Record<string, Text> = {
  confirm_product: { en: "Confirm which listed product matches yours.", hi: "पुष्टि करें कि कौन-सा सूचीबद्ध उत्पाद आपका है।" },
  verify_status: { en: "Verify the listing status on the official BIS page.", hi: "आधिकारिक BIS पृष्ठ पर सूची की स्थिति सत्यापित करें।" },
  prepare_before_enforcement: { en: "Prepare for certification before the enforcement date ({date}).", hi: "लागू तिथि ({date}) से पहले प्रमाणन की तैयारी करें।" },
  obtain_standard: { en: "Obtain {std_key} from the BIS standards portal.", hi: "BIS मानक पोर्टल से {std_key} प्राप्त करें।" },
  read_product_manual: { en: "Read the Product Manual “{title}”.", hi: "उत्पाद मैनुअल “{title}” पढ़ें।" },
  test_at_listed_lab: { en: "Get samples tested at a LIMS-listed laboratory ({count} found).", hi: "LIMS-सूचीबद्ध प्रयोगशाला में नमूनों का परीक्षण कराएँ ({count} मिलीं)।" },
  search_lims: { en: "Search the official LIMS portal for laboratories.", hi: "प्रयोगशालाओं के लिए आधिकारिक LIMS पोर्टल खोजें।" },
  apply_online: { en: "Apply online on Manakonline.", hi: "मानकऑनलाइन पर ऑनलाइन आवेदन करें।" },
  check_official_listing: { en: "Check the official list of products under compulsory certification.", hi: "अनिवार्य प्रमाणन वाले उत्पादों की आधिकारिक सूची देखें।" },
};

export const EFFECTS: Record<string, Text> = {
  COMPULSORY: { en: "Compulsory (listed)", hi: "अनिवार्य (सूचीबद्ध)" },
  UPCOMING: { en: "Notified — not yet in force", hi: "अधिसूचित — अभी लागू नहीं" },
  ENFORCEMENT_DATE_REACHED: { en: "Enforcement date reached — verify", hi: "लागू तिथि आ गई — पुष्टि करें" },
  DENOTIFIED: { en: "De-notified", hi: "विअधिसूचित" },
  RESCINDED: { en: "Rescinded — verify", hi: "निरस्त — पुष्टि करें" },
  NEEDS_VERIFICATION: { en: "Needs verification", hi: "पुष्टि आवश्यक" },
  NO_LISTING_FOUND: { en: "No listing found", hi: "कोई सूची नहीं मिली" },
};

export function pick(entry: Text | undefined, lang: Lang, fallback: string, vars?: Record<string, unknown>): string {
  let text = entry ? entry[lang] : fallback;
  for (const [key, value] of Object.entries(vars ?? {})) text = text.replaceAll(`{${key}}`, String(value ?? ""));
  return text;
}

export const EFFECT_TONE: Record<string, string> = {
  COMPULSORY: "LISTED_COMPULSORY",
  UPCOMING: "UPCOMING",
  ENFORCEMENT_DATE_REACHED: "NEEDS_VERIFICATION",
  DENOTIFIED: "DENOTIFIED",
  RESCINDED: "RESCINDED",
  NEEDS_VERIFICATION: "NEEDS_VERIFICATION",
};

export const STATES_AND_UTS = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
  "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
  "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
  "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
  "Ladakh", "Lakshadweep", "Puducherry",
];
