import streamlit as st
import pandas as pd
import requests
import time
import re
import json
import streamlit.components.v1 as components

# --- SAYFA YAPILANDIRMASI ---
st.set_page_config(
    page_title="Mai Studios - Akıllı Vitrin & Koleksiyon Sıralayıcı",
    page_icon="✨",
    layout="wide"
)

# --- CSS STİLLERİ ---
st.markdown("""
<style>
    [data-testid="stDataFrame"] img {
        height: 100% !important;
        max-height: 48px !important;
        width: auto !important;
        object-fit: contain !important;
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.15);
    }
</style>
""", unsafe_allow_html=True)

# --- SHOPIFY GRAPHQL API AYARLARI ---
SHOPIFY_STORE = "mai-turkiye.myshopify.com"
ACCESS_TOKEN = "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"
API_VERSION = "2024-07"
GRAPHQL_URL = f"https://{SHOPIFY_STORE}/admin/api/{API_VERSION}/graphql.json"

HEADERS = {
    "X-Shopify-Access-Token": ACCESS_TOKEN,
    "Content-Type": "application/json"
}

def run_graphql_query(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        response = requests.post(GRAPHQL_URL, json=payload, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if "errors" in result:
                st.error(f"GraphQL Hatası: {result['errors']}")
                return None
            return result
        else:
            st.error(f"API Hatası ({response.status_code}): {response.text}")
            return None
    except Exception as e:
        st.error(f"Bağlantı Hatası: {e}")
        return None

# --- 1. KOLEKSİYONLARI ÇEKME ---
@st.cache_data(ttl=60)
def get_collections():
    collections = []
    has_next_page = True
    cursor = None

    while has_next_page:
        cursor_str = f', after: "{cursor}"' if cursor else ""
        query = f"""
        {{
            collections(first: 250{cursor_str}) {{
                pageInfo {{
                    hasNextPage
                    endCursor
                }}
                edges {{
                    node {{
                        id
                        title
                        productsCount {{
                            count
                        }}
                    }}
                }}
            }}
        }}
        """
        res = run_graphql_query(query)
        if res and "data" in res and "collections" in res["data"]:
            data = res["data"]["collections"]
            for edge in data.get("edges", []):
                node = edge.get("node", {})
                prod_count = node.get("productsCount")
                count_val = prod_count.get("count", 0) if prod_count else 0
                collections.append({
                    "id": node.get("id"),
                    "title": node.get("title"),
                    "count": count_val
                })
            page_info = data.get("pageInfo", {})
            has_next_page = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
        else:
            break

    return collections

# --- MODEL, RENK VE SEZON TESPİTİ ---
COLORS_LIST = [
    "SIYAH", "BEYAZ", "EKRU", "KREMA", "BEJ", "KAHVERENGI", "KAHVE", "LACIVERT", "MAVI", 
    "KIRMIZI", "YESIL", "HAKI", "BORDO", "PEMBE", "TURUNCU", "ORANJ", "SARI", "GRI", 
    "LILA", "ANTRASIT", "VIZON", "KIREMIT", "MINT", "INDIGO", "FUKSYA", "TEN", "CAMEL", "SOMON"
]

GENERIC_CATEGORY_WORDS = {
    "GOMLEK", "SORT", "TAKIM", "PANTOLON", "ELBISE", "ETEK", "CEKET", "BLUZ", "TOP", 
    "TRIKO", "YELEK", "HIRKA", "KABAN", "MONT", "BODY", "TULUM", "KIMONO", "SWEATSHIRT"
}

def turkish_upper(text):
    if not text:
        return ""
    return (str(text).replace("i", "İ").replace("ı", "I").upper()
            .replace("İ", "I").replace("Ç", "C").replace("Ş", "S")
            .replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O"))

def extract_color(title, tags):
    full_text = turkish_upper(str(title) + " " + " ".join([str(t) for t in tags]))
    for col in COLORS_LIST:
        if re.search(r'\b' + col + r'\b', full_text):
            return col
    return "DIGER"

def extract_model_base(title):
    clean = turkish_upper(title)
    for c in COLORS_LIST:
        clean = re.sub(r'\b' + c + r'\b', '', clean)
    clean_alphanumeric = re.sub(r'[^A-Z0-9\s]', ' ', clean)
    words = [w for w in clean_alphanumeric.split() if w not in GENERIC_CATEGORY_WORDS]
    if words:
        return words[0]
    raw_words = clean_alphanumeric.split()
    return raw_words[0] if raw_words else "GENEL"

def detect_season(tags_list):
    text = turkish_upper(" ".join([str(t) for t in tags_list]))
    is_summer = any(k in text for k in ["SS", "YAZ", "SUMMER", "SPRING", "ILKBAHAR"])
    is_winter = any(k in text for k in ["FW", "AW", "KIS", "WINTER", "SONBAHAR", "FALL"])
    if is_summer and is_winter:
        return "Multi Sezon"
    elif is_summer:
        return "Yaz (SS)"
    elif is_winter:
        return "Kış (FW)"
    return "Multi Sezon"

# --- 2. ÜRÜNLERİ, GÖRSELLERİ VE CANLI SIRAYI ÇEKME ---
@st.cache_data(ttl=120)
def get_collection_data_fast(collection_id):
    products = []
    has_next_page = True
    cursor = None

    query_manual = """
    query getCollectionProducts($id: ID!, $cursor: String) {
      collection(id: $id) {
        products(first: 100, after: $cursor, sortKey: COLLECTION_DEFAULT) {
          pageInfo {
            hasNextPage
            endCursor
          }
          edges {
            node {
              id
              title
              tags
              createdAt
              updatedAt
              totalInventory
              images(first: 1) {
                edges {
                  node {
                    url
                  }
                }
              }
              variants(first: 25) {
                edges {
                  node {
                    title
                    sku
                    price
                    compareAtPrice
                    inventoryQuantity
                  }
                }
              }
            }
          }
        }
      }
    }
    """

    while has_next_page:
        variables = {"id": collection_id, "cursor": cursor}
        res = run_graphql_query(query_manual, variables)
        if not res or "data" not in res or not res["data"]["collection"]:
            break
        
        prod_data = res["data"]["collection"]["products"]
        for edge in prod_data["edges"]:
            p = edge["node"]
            tags = p.get("tags", [])
            variants = edge["node"]["variants"]["edges"]
            
            img_url = ""
            img_edges = p.get("images", {}).get("edges", [])
            if img_edges:
                raw_url = img_edges[0]["node"].get("url", "")
                if ".jpg" in raw_url:
                    img_url = raw_url.replace(".jpg", "_250x330_crop_center.jpg")
                elif ".png" in raw_url:
                    img_url = raw_url.replace(".png", "_250x330_crop_center.png")
                else:
                    img_url = raw_url

            total_sizes = len(variants)
            active_sizes = 0
            first_price = 0.0
            compare_price = 0.0
            first_sku = variants[0]["node"].get("sku") or "" if variants else ""
            all_skus = [v["node"].get("sku") for v in variants if v["node"].get("sku")]
            
            if variants:
                first_node = variants[0]["node"]
                first_price = float(first_node.get("price") or 0.0)
                compare_price = float(first_node.get("compareAtPrice") or 0.0)
                
            for v in variants:
                qty = v["node"].get("inventoryQuantity") or 0
                if qty > 0:
                    active_sizes += 1
            
            discount_pct = 0.0
            if compare_price > first_price and compare_price > 0:
                discount_pct = round(((compare_price - first_price) / compare_price) * 100, 1)

            if active_sizes == 0:
                size_status = "Tükendi"
            elif active_sizes == 1 and total_sizes > 1:
                size_status = "Tek Beden"
            elif active_sizes < total_sizes and active_sizes <= (total_sizes / 2):
                size_status = "Kırık Beden"
            else:
                size_status = "Tam Beden"

            products.append({
                "product_id": p["id"],
                "image": img_url,
                "title": p["title"],
                "sku": first_sku,
                "all_skus": all_skus,
                "tags": tags,
                "season": detect_season(tags),
                "model_base": extract_model_base(p["title"]),
                "color": extract_color(p["title"], tags),
                "total_stock": p.get("totalInventory", 0),
                "total_sizes": total_sizes,
                "active_sizes": active_sizes,
                "size_status": size_status,
                "price": first_price,
                "discount_pct": discount_pct,
                "created_at": p.get("createdAt"),
                "updated_at": p.get("updatedAt")
            })
        
        has_next_page = prod_data["pageInfo"]["hasNextPage"]
        cursor = prod_data["pageInfo"]["endCursor"]

    df_res = pd.DataFrame(products)
    if df_res.empty:
        return df_res

    now_utc = pd.Timestamp.now(tz="UTC")
    df_res["created_dt"] = pd.to_datetime(df_res["created_at"], utc=True)
    df_res["updated_dt"] = pd.to_datetime(df_res["updated_at"], utc=True)
    df_res["days_old"] = (now_utc - df_res["created_dt"]).dt.days
    df_res["days_since_update"] = (now_utc - df_res["updated_dt"]).dt.days

    best_selling_order = {}
    query_bs = """
    query getBestSelling($id: ID!) {
      collection(id: $id) {
        products(first: 250, sortKey: BEST_SELLING) {
          edges {
            node {
              id
            }
          }
        }
      }
    }
    """
    res_bs = run_graphql_query(query_bs, {"id": collection_id})
    if res_bs and "data" in res_bs and res_bs["data"]["collection"]:
        edges = res_bs["data"]["collection"]["products"]["edges"]
        total_p = len(edges)
        for idx, edge in enumerate(edges):
            score = round(((total_p - idx) / total_p) * 100, 1) if total_p > 1 else 100
            best_selling_order[edge["node"]["id"]] = score

    df_res["shopify_sales_score"] = df_res["product_id"].map(best_selling_order).fillna(20.0)
    return df_res

# --- 3. GELİŞMİŞ 4'LÜ IZGARA MODEL/RENK AYRIŞTIRMA MOTORU ---
def diversify_grid_4(df_in, lookback=4):
    in_stock = df_in[df_in["total_stock"] > 0].to_dict("records")
    out_of_stock = df_in[df_in["total_stock"] <= 0].to_dict("records")
    result = []
    
    while in_stock:
        recent_window = result[-lookback:] if len(result) >= lookback else result
        recent_models = [r["model_base"] for r in recent_window]
        recent_colors = [r["color"] for r in recent_window if r["color"] != "DIGER"]
        
        chosen_idx = None
        
        for i, item in enumerate(in_stock):
            m_ok = item["model_base"] not in recent_models
            c_ok = (item["color"] == "DIGER") or (item["color"] not in recent_colors)
            if m_ok and c_ok:
                chosen_idx = i
                break
        
        if chosen_idx is None:
            for i, item in enumerate(in_stock):
                if item["model_base"] not in recent_models:
                    chosen_idx = i
                    break
        
        if chosen_idx is None and len(result) > 0:
            last_m = result[-1]["model_base"]
            for i, item in enumerate(in_stock):
                if item["model_base"] != last_m:
                    chosen_idx = i
                    break
                    
        if chosen_idx is None:
            chosen_idx = 0
            
        result.append(in_stock.pop(chosen_idx))
        
    result.extend(out_of_stock)
    return pd.DataFrame(result)

# --- 4. CANLIYA ALMA MUTASYONU ---
def reorder_shopify_collection(collection_id, product_ids, show_progress=True):
    mutation = """
    mutation collectionReorderProducts($id: ID!, $moves: [MoveInput!]!) {
      collectionReorderProducts(id: $id, moves: $moves) {
        job {
          id
          done
        }
        userErrors {
          field
          message
        }
      }
    }
    """
    moves = [{"id": pid, "newPosition": str(idx)} for idx, pid in enumerate(product_ids)]
    batch_size = 250
    total_moves = len(moves)
    progress_bar = st.progress(0) if show_progress else None
    
    for i in range(0, total_moves, batch_size):
        batch = moves[i:i + batch_size]
        variables = {"id": collection_id, "moves": batch}
        res = run_graphql_query(mutation, variables)
        if res and "data" in res:
            errors = res["data"]["collectionReorderProducts"].get("userErrors", [])
            if errors:
                st.error(f"Sıralama Hatası: {errors}")
                return False
        time.sleep(0.2)
        if progress_bar:
            progress_bar.progress(min((i + batch_size) / total_moves, 1.0))
        
    return True

# --- TOPLU KOLEKSİYONLAR İÇİN HIZLI SIRALAMA & TEMİZLEME MOTORU ---
def push_out_of_stock_for_collection(collection_id):
    has_next = True
    cursor = None
    items = []
    
    query_simple = """
    query getColSimple($id: ID!, $cursor: String) {
      collection(id: $id) {
        products(first: 250, after: $cursor, sortKey: COLLECTION_DEFAULT) {
          pageInfo {
            hasNextPage
            endCursor
          }
          edges {
            node {
              id
              totalInventory
            }
          }
        }
      }
    }
    """
    while has_next:
        res = run_graphql_query(query_simple, {"id": collection_id, "cursor": cursor})
        if not res or "data" not in res or not res["data"]["collection"]:
            break
        prod_data = res["data"]["collection"]["products"]
        for edge in prod_data["edges"]:
            node = edge["node"]
            items.append({
                "id": node["id"],
                "stock": node.get("totalInventory", 0)
            })
        has_next = prod_data["pageInfo"]["hasNextPage"]
        cursor = prod_data["pageInfo"]["endCursor"]

    if not items:
        return True

    in_stock_ids = [it["id"] for it in items if it["stock"] > 0]
    out_of_stock_ids = [it["id"] for it in items if it["stock"] <= 0]
    final_ids = in_stock_ids + out_of_stock_ids
    
    return reorder_shopify_collection(collection_id, final_ids, show_progress=False)

# ==================== KONTROL PANELİ ====================
st.sidebar.title("⚙️ Kontrol Paneli")

collections = get_collections()
if not collections:
    st.sidebar.error("Koleksiyonlar yüklenemedi.")
    st.stop()

# ==================== 🚀 TOPLU VİTRİN TEMİZLİĞİ ====================
with st.sidebar.expander("🚀 Toplu Vitrin Temizliği (Tüm Koleksiyonlar)", expanded=False):
    st.caption("Seçilen koleksiyonların mevcut vitrin sırasını bozmadan tükenenleri en arkaya atar, stokluları hemen önünde toplar:")
    
    col_names = [f"{c['title']} ({c['count']} Ürün)" for c in collections]
    name_to_id = {f"{c['title']} ({c['count']} Ürün)": c["id"] for c in collections}
    
    btn_sel_all, btn_clear_all = st.columns(2)
    with btn_sel_all:
        if st.button("✅ Tümünü Seç", use_container_width=True):
            st.session_state["bulk_selected_cols"] = col_names
            st.rerun()
    with btn_clear_all:
        if st.button("❌ Temizle", use_container_width=True):
            st.session_state["bulk_selected_cols"] = []
            st.rerun()

    default_bulk = st.session_state.get("bulk_selected_cols", [])
    bulk_cols_chosen = st.multiselect(
        "Temizlenecek Koleksiyonları Belirleyin:",
        options=col_names,
        default=default_bulk
    )

    if st.button("⚡ Seçilenlerde Tükenenleri Sona At & Canlıya Al", type="primary", use_container_width=True):
        if not bulk_cols_chosen:
            st.warning("Lütfen en az bir koleksiyon seçin.")
        else:
            bulk_progress = st.progress(0)
            status_text = st.empty()
            total_selected = len(bulk_cols_chosen)
            
            for idx, c_name in enumerate(bulk_cols_chosen):
                c_id = name_to_id[c_name]
                clean_title = c_name.split(" (")[0]
                status_text.text(f"⏳ İşleniyor ({idx+1}/{total_selected}): {clean_title}")
                push_out_of_stock_for_collection(c_id)
                bulk_progress.progress((idx + 1) / total_selected)
                time.sleep(0.2)
                
            status_text.empty()
            st.cache_data.clear()
            st.success(f"🎉 Harika! Seçilen {total_selected} koleksiyonun tamamında tükenenler sırayı bozmadan sona taşındı ve vitrinler güncellendi!")
            st.balloons()

st.sidebar.divider()

# ==================== TEKİL KOLEKSİYON SEÇİMİ ====================
col_options = {f"{c['title']} ({c['count']} Ürün)": c["id"] for c in collections}
options_list = ["-- Lütfen Bir Koleksiyon Seçin veya Arayın --"] + list(col_options.keys())

selected_col_label = st.sidebar.selectbox(
    "🔍 Koleksiyon Ara ve Seç:",
    options=options_list,
    index=0,
    help="Kutuya tıklayıp aradığınız koleksiyonun adını doğrudan klavyeden yazabilirsiniz."
)

if st.sidebar.button("⚡ Canlı Verileri Yenile", use_container_width=True):
    st.cache_data.clear()
    # Oturumdaki tüm eski koleksiyon çalışma listelerini temizle
    keys_to_clear = [k for k in st.session_state.keys() if k.startswith("working_") or k.startswith("orig_") or k.startswith("filters_hash_")]
    for k in keys_to_clear:
        del st.session_state[k]
    st.rerun()

if selected_col_label == "-- Lütfen Bir Koleksiyon Seçin veya Arayın --":
    st.title("🛍️ Mai Studios - Akıllı Vitrin Düzenleyici")
    st.info("👈 İşleme başlamak için sol taraftaki kutudan bir koleksiyon arayıp seçin veya en üstteki 'Toplu Vitrin Temizliği' panelini kullanın.")
    st.stop()

selected_col_id = col_options[selected_col_label]

with st.spinner("Koleksiyon ürünleri ve canlı vitrin sırası çekiliyor..."):
    df_raw = get_collection_data_fast(selected_col_id)

if df_raw.empty:
    st.warning("Bu koleksiyonda ürün bulunamadı.")
    st.stop()

session_key = f"orig_{selected_col_id}"
working_key = f"working_{selected_col_id}"

if session_key not in st.session_state:
    df_backup = df_raw.copy()
    df_backup["Mevcut Sıra"] = df_backup.index + 1
    st.session_state[session_key] = df_backup

st.sidebar.divider()

# --- 🚀 HIZLI STRATEJİLER ---
st.sidebar.subheader("⚡ Hızlı Filtreleme & Öncelikler")
st.sidebar.caption("İstediğin filtreleri açarak yeni sıralamayı oluşturabilirsin:")

f_sales = st.sidebar.checkbox("🔥 Çok Satanlar Öne Çıksın", value=False)
f_stock = st.sidebar.checkbox("📦 Bol Stoklular Öne Çıksın (Bedene Bakmadan)", value=False)
f_new = st.sidebar.checkbox("✨ Yeni Eklenenler Öne Çıksın", value=False)
f_recent_stock = st.sidebar.checkbox("🔄 Stoğu Yeni Gelenler Öne Çıksın", value=False)
f_discount = st.sidebar.checkbox("🏷️ İndirimliler Öne Çıksın", value=False)

f_season = st.sidebar.checkbox("❄️/☀️ Sezon Önceliği Uygula", value=False)
selected_priority_seasons = []
if f_season:
    selected_priority_seasons = st.sidebar.multiselect(
        "Öne Çıkacak Sezonları Seçin:",
        options=["Kış (FW)", "Yaz (SS)", "Multi Sezon"],
        default=["Kış (FW)", "Multi Sezon"]
    )

st.sidebar.divider()

# --- VİTRİN HİJYENİ VE KORUMA ---
st.sidebar.subheader("🛡️ Vitrin Kuralları")
push_out_of_stock = st.sidebar.checkbox("🚫 Tükenenleri (0 Stok) En Sona At", value=False)
enable_clustering_fix = st.sidebar.checkbox("🎨 4'lü Izgarada Model/Renk Ayrıştır", value=False)
enable_broken_penalty = st.sidebar.checkbox("⚠️ Kırık Bedenleri Cezalandır", value=False)
enable_single_penalty = st.sidebar.checkbox("⚠️ Tek Beden Kalanları Cezalandır", value=False)

# --- DETAYLI AYARLAR ---
with st.sidebar.expander("🛠️ Detaylı Ağırlık ve Ceza Ayarları"):
    sales_weight = st.slider("Satış Performansı Ağırlığı (%)", 0, 100, 45) if f_sales else 0
    stock_weight = st.slider("Stok Hacmi Ağırlığı (%)", 0, 100, 40) if f_stock else 0
    
    if f_new:
        new_days = st.slider("Yeni Gelen Eşiği (Gün)", 1, 60, 20)
        new_bonus = st.slider("Yeni Gelen Bonus Puanı", 0, 100, 30)
    else:
        new_days, new_bonus = 0, 0
        
    if f_recent_stock:
        recent_stock_bonus = st.slider("Stok Güncelleme Bonusu", 0, 60, 25)
    else:
        recent_stock_bonus = 0
        
    if f_season and selected_priority_seasons:
        season_bonus = st.slider("Sezon Bonusu", 0, 100, 35)
    else:
        season_bonus = 0
        
    if f_discount:
        discount_weight = st.slider("İndirim Ağırlığı (%)", 0, 100, 20)
        min_discount_filter = st.slider("Minimum İndirim Eşiği (%)", 0, 80, 0)
    else:
        discount_weight, min_discount_filter = 0, 0
        
    broken_penalty = st.slider("Kırık Beden Cezası", 0, 60, 20) if enable_broken_penalty else 0
    single_penalty = st.slider("Tek Beden Cezası", 0, 80, 35) if enable_single_penalty else 0
    
    enable_exclude = st.checkbox("İstemediğim Ürünleri Gizle/Çıkar", value=False)
    excluded_keywords = st.text_area("Hariç tutulacak kelimeler (virgülle ayırın):", placeholder="numune, defolu, hediye") if enable_exclude else ""

# --- YEDEK VE DOSYALAR ---
with st.sidebar.expander("💾 Orijinal Sıra & Yedek İşlemleri"):
    if st.button("⏪ Canlı Vitrin Sırasına Sıfırla"):
        st.session_state[working_key] = st.session_state[session_key].copy()
        st.rerun()

    orig_df = st.session_state[session_key]
    csv_data = orig_df[["Mevcut Sıra", "product_id", "title", "sku", "price", "total_stock"]].to_csv(index=False).encode('utf-8')
    st.download_button(label="📥 Mevcut Sırayı CSV İndir", data=csv_data, file_name=f"yedek_{selected_col_label.split(' (')[0]}_{time.strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")
    uploaded_backup = st.file_uploader("📤 Eski Yedek CSV Yükle", type=["csv"])
    sales_file = st.file_uploader("📈 Opsiyonel Satış Excel/CSV:", type=["xlsx", "xls", "csv"])

# ==================== HESAPLAMA MOTORU ====================
df = df_raw.copy()
df["Mevcut Sıra"] = df.index + 1

if enable_exclude and excluded_keywords:
    kws = [k.strip().lower() for k in excluded_keywords.split(",") if k.strip()]
    for kw in kws:
        df = df[~df["title"].str.lower().str.contains(kw) & ~df["tags"].apply(lambda tg: any(kw in str(t).lower() for t in tg))]

if f_discount and min_discount_filter > 0:
    df = df[df["discount_pct"] >= min_discount_filter]

df["file_sales"] = 0
if sales_file:
    try:
        s_df = pd.read_csv(sales_file) if sales_file.name.endswith(".csv") else pd.read_excel(sales_file)
        sku_col = next((c for c in s_df.columns if any(k in str(c).lower() for k in ["sku", "barkod", "kod"])), None)
        qty_col = next((c for c in s_df.columns if any(k in str(c).lower() for k in ["adet", "miktar", "satış"])), None)
        if sku_col and qty_col:
            s_df[qty_col] = pd.to_numeric(s_df[qty_col], errors="coerce").fillna(0)
            sku_map = s_df.groupby(sku_col)[qty_col].sum().to_dict()
            df["file_sales"] = df["sku"].map(sku_map).fillna(0)
            df["shopify_sales_score"] = (df["file_sales"] / (df["file_sales"].max() or 1)) * 100
            st.sidebar.success("✅ Satış raporu entegre edildi!")
    except Exception:
        pass

max_stock = df["total_stock"].max() if df["total_stock"].max() > 0 else 1

def compute_combined_score(r):
    score = 0.0
    if f_sales:
        score += (r["shopify_sales_score"]) * (sales_weight / 100.0)
    if f_stock:
        score += (r["total_stock"] / max_stock) * stock_weight
    if f_new and r["days_old"] <= new_days:
        score += new_bonus
    if f_recent_stock and r["days_since_update"] <= 5:
        score += recent_stock_bonus
    if f_season and r["season"] in selected_priority_seasons:
        score += season_bonus
    if f_discount:
        score += (r["discount_pct"] / 100.0) * discount_weight
    if enable_broken_penalty and r["size_status"] == "Kırık Beden":
        score -= broken_penalty
    if enable_single_penalty and r["size_status"] == "Tek Beden":
        score -= single_penalty
    return score

other_active_rules = any([
    f_sales, f_stock, f_new, f_recent_stock, 
    (f_season and selected_priority_seasons), f_discount, 
    enable_broken_penalty, enable_single_penalty
])

any_active = other_active_rules or push_out_of_stock or enable_clustering_fix
current_filters_hash = f"{any_active}_{f_sales}_{f_stock}_{f_new}_{f_recent_stock}_{f_season}_{selected_priority_seasons}_{f_discount}_{enable_broken_penalty}_{enable_single_penalty}_{push_out_of_stock}_{enable_clustering_fix}"
last_filters_key = f"filters_hash_{selected_col_id}"

# ÇALIŞMA LİSTESİ BELİRLEME
if working_key not in st.session_state:
    st.session_state[working_key] = st.session_state[session_key].copy()
    st.session_state[last_filters_key] = current_filters_hash

if st.session_state.get(last_filters_key) != current_filters_hash:
    st.session_state[last_filters_key] = current_filters_hash
    
    if uploaded_backup is not None:
        try:
            b_df = pd.read_csv(uploaded_backup)
            if "product_id" in b_df.columns:
                id_order = {pid: idx for idx, pid in enumerate(b_df["product_id"])}
                df["backup_pos"] = df["product_id"].map(id_order).fillna(999999)
                df_sorted = df.sort_values(by="backup_pos").reset_index(drop=True)
            else:
                df_sorted = df.copy()
        except Exception:
            df_sorted = df.copy()
            
    elif not any_active:
        df_sorted = st.session_state[session_key].copy()
        
    elif not other_active_rules and push_out_of_stock and not enable_clustering_fix:
        base_df = st.session_state[session_key].copy()
        in_stock_df = base_df[base_df["total_stock"] > 0]
        out_of_stock_df = base_df[base_df["total_stock"] <= 0]
        df_sorted = pd.concat([in_stock_df, out_of_stock_df]).reset_index(drop=True)
        
    else:
        if other_active_rules:
            df["Hesaplanan Skor"] = df.apply(compute_combined_score, axis=1)
            if push_out_of_stock:
                in_stock_df = df[df["total_stock"] > 0].sort_values(by="Hesaplanan Skor", ascending=False)
                out_of_stock_df = df[df["total_stock"] <= 0].sort_values(by="Hesaplanan Skor", ascending=False)
                df_sorted = pd.concat([in_stock_df, out_of_stock_df]).reset_index(drop=True)
            else:
                df_sorted = df.sort_values(by="Hesaplanan Skor", ascending=False).reset_index(drop=True)
        else:
            base_df = st.session_state[session_key].copy()
            if push_out_of_stock:
                in_stock_df = base_df[base_df["total_stock"] > 0]
                out_of_stock_df = base_df[base_df["total_stock"] <= 0]
                df_sorted = pd.concat([in_stock_df, out_of_stock_df]).reset_index(drop=True)
            else:
                df_sorted = base_df

    if enable_clustering_fix and uploaded_backup is None:
        df_sorted = diversify_grid_4(df_sorted, lookback=4)

    st.session_state[working_key] = df_sorted

# Planlanan sırayı güncelle
df_sorted = st.session_state[working_key].copy().reset_index(drop=True)
df_sorted["Planlanan Sıra"] = df_sorted.index + 1

# ==================== ANA EKRAN ====================
st.title(f"🛍️ {selected_col_label.split(' (')[0]}")

active_badges = []
if f_sales: active_badges.append("🔥 Çok Satanlar")
if f_stock: active_badges.append("📦 Bol Stoklular")
if f_new: active_badges.append("✨ Yeni Eklenenler")
if f_recent_stock: active_badges.append("🔄 Stoğu Yenilenenler")
if f_season and selected_priority_seasons: active_badges.append(f"❄️/☀️ Sezon: {', '.join(selected_priority_seasons)}")
if f_discount: active_badges.append("🏷️ İndirim Oranı")
if push_out_of_stock: active_badges.append("🚫 0 Stok Sonda")
if enable_clustering_fix: active_badges.append("🎨 4'lü Izgara Ayrıştırma")

if active_badges:
    st.success(f"⚡ **Aktif Filtreler:** {' + '.join(active_badges)}")
else:
    st.info("👁️ **Mevcut Canlı Vitrin:** Şu an Shopify'da müşterilerin gördüğü birebir sıra listeleniyor.")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Toplam Ürün", len(df_sorted))
m2.metric("Tam Beden", len(df_sorted[df_sorted["size_status"] == "Tam Beden"]))
m3.metric("Kırık Beden", len(df_sorted[df_sorted["size_status"] == "Kırık Beden"]))
m4.metric("Tek Beden", len(df_sorted[df_sorted["size_status"] == "Tek Beden"]))
m5.metric("Tükenen (0 Stok)", len(df_sorted[df_sorted["total_stock"] <= 0]))

st.divider()

# ==================== GÖRSEL IZGARA & MANUEL TAŞIMA ====================
st.subheader("🎨 Akıllı Görsel Vitrin (Sortmax Modeli)")

c_srch, c_view = st.columns([3, 1])
with c_srch:
    filter_q = st.text_input("🔍 Vitrinde Ürün / Model Ara (Örn: Aliza, Seyseller, Takım):", placeholder="Model veya renk aratıp sırasını bulabilirsiniz...")
with c_view:
    view_mode = st.radio("Görünüm Modu:", ["🎨 Görsel Vitrin (Sortmax)", "📋 Klasik Tablo"], horizontal=True)

# Arama Filtrelemesi
grid_df = df_sorted.copy()
if filter_q:
    fq = filter_q.strip().lower()
    grid_df = grid_df[grid_df["title"].str.lower().str.contains(fq) | grid_df["sku"].str.lower().str.contains(fq)]

# ==================== 🚀 HEDEF SIRAYA TAŞIMA BAR ====================
search_options = [f"#{r['Planlanan Sıra']} - {r['title']} ({r['color']})" for _, r in grid_df.iterrows()]

t_c1, t_c2, t_c3 = st.columns([3, 1, 1.2])
with t_c1:
    selected_move_items = st.multiselect(
        "📌 Taşınacak Ürün(ler)i Seçin:",
        options=search_options,
        placeholder="Taşımak istediğiniz ürünü seçin..."
    )
with t_c2:
    new_target_pos = st.number_input("Hedef Sıra No:", min_value=1, max_value=len(df_sorted), value=1)
with t_c3:
    st.write("")
    st.write("")
    if st.button("🚀 Hedef Sıraya Taşı", type="primary", use_container_width=True):
        if selected_move_items:
            ranks_to_move = [int(item.split(" - ")[0].replace("#", "")) for item in selected_move_items]
            curr = st.session_state[working_key].copy().reset_index(drop=True)
            curr["Planlanan Sıra"] = curr.index + 1
            
            chosen_rows = curr[curr["Planlanan Sıra"].isin(ranks_to_move)]
            remaining_rows = curr[~curr["Planlanan Sıra"].isin(ranks_to_move)]
            
            insert_idx = max(0, min(new_target_pos - 1, len(remaining_rows)))
            new_full_df = pd.concat([
                remaining_rows.iloc[:insert_idx],
                chosen_rows,
                remaining_rows.iloc[insert_idx:]
            ]).reset_index(drop=True)
            
            st.session_state[working_key] = new_full_df
            st.success(f"✅ Seçilen ürün(ler) başarıyla {new_target_pos}. sıraya yerleştirildi!")
            st.rerun()
        else:
            st.warning("Lütfen taşınacak en az bir ürün seçin.")

# ==================== 🧲 SÜRÜKLE-BIRAK DEĞİŞİKLİKLERİNİ KAYDETME KÖPRÜSÜ ====================
with st.expander("💾 Sürükle-Bırak ile Yaptığım Değişiklikleri Kalıcı Kaydet", expanded=False):
    st.caption("Aşağıdaki kartları fareyle sürükleyerek yerlerini değiştirdiyseniz, bu sırayı Shopify'a göndermeden önce hafızaya mühürlemek için butona basın:")
    sync_order_json = st.text_area("Sürüklenen Sıra Verisi (Otomatik Kopyalanır):", key="dragged_ids_area", height=68, placeholder="Aşağıdan kartları sürüklediğinizde bu kutu otomatik dolar...")
    if st.button("📥 Sürüklenen Görsel Sırayı Kesinleştir & Listeye Kaydet", use_container_width=True):
        if sync_order_json:
            try:
                new_ordered_ids = json.loads(sync_order_json)
                curr = st.session_state[working_key].copy()
                id_map = {pid: idx for idx, pid in enumerate(new_ordered_ids)}
                curr["sort_temp"] = curr["product_id"].map(id_map).fillna(999999)
                st.session_state[working_key] = curr.sort_values(by="sort_temp").drop(columns=["sort_temp"]).reset_index(drop=True)
                st.success("🎉 Sürüklediğiniz vitrin sırası başarıyla kaydedildi!")
                st.rerun()
            except Exception as e:
                st.error(f"Sıra işlenirken hata: {e}")

st.caption("💡 **Sortmax Tarzı Kullanım:** Kartları fareyle istediğiniz yere sürükleyin. Sürükleme bittiğinde sol üstteki numaralar `#1, #2, #3...` diye anında güncellenir.")

if view_mode == "🎨 Görsel Vitrin (Sortmax)":
    cards_data = []
    for idx, row in grid_df.iterrows():
        cards_data.append({
            "id": row["product_id"],
            "title": row["title"],
            "image": row["image"] if row["image"] else "",
            "color": row["color"],
            "stock": int(row["total_stock"]),
            "status": row["size_status"],
            "season": row["season"],
            "discount": float(row["discount_pct"]),
            "actual_rank": int(row["Planlanan Sıra"])
        })
    
    cards_json = json.dumps(cards_data)
    
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js"></script>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 4px;
                background: #f8fafc;
            }}
            .grid-container {{
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 8px;
                padding: 4px;
            }}
            .product-card {{
                background: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                overflow: hidden;
                box-shadow: 0 1px 2px rgba(0,0,0,0.05);
                cursor: grab;
                transition: transform 0.1s ease, box-shadow 0.1s ease, border-color 0.1s ease;
                display: flex;
                flex-direction: column;
                user-select: none;
                position: relative;
            }}
            .product-card:active {{
                cursor: grabbing;
            }}
            .product-card.sortable-selected {{
                border: 2px solid #2563eb !important;
                background: #eff6ff !important;
                box-shadow: 0 2px 8px rgba(37,99,235,0.25) !important;
            }}
            .img-container {{
                width: 100%;
                height: 125px;
                background: #f1f5f9;
                position: relative;
                display: flex;
                align-items: center;
                justify-content: center;
                overflow: hidden;
            }}
            .img-container img {{
                width: 100%;
                height: 100%;
                object-fit: cover;
                object-position: center top;
            }}
            .badge-order {{
                position: absolute;
                top: 4px;
                left: 4px;
                background: rgba(15, 23, 42, 0.9);
                color: #ffffff;
                font-size: 10px;
                font-weight: 700;
                padding: 2px 6px;
                border-radius: 4px;
                z-index: 2;
                box-shadow: 0 1px 3px rgba(0,0,0,0.3);
            }}
            .badge-discount {{
                position: absolute;
                top: 4px;
                right: 4px;
                background: #e11d48;
                color: #ffffff;
                font-size: 9px;
                font-weight: 700;
                padding: 2px 5px;
                border-radius: 3px;
                z-index: 2;
            }}
            .card-details {{
                padding: 5px 6px;
                display: flex;
                flex-direction: column;
                gap: 3px;
                background: #ffffff;
            }}
            .product-title {{
                font-size: 10px;
                font-weight: 600;
                color: #1e293b;
                line-height: 1.15;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }}
            .tags-row {{
                display: flex;
                flex-wrap: wrap;
                gap: 2px;
                align-items: center;
            }}
            .tag {{
                font-size: 8.5px;
                font-weight: 600;
                padding: 1px 4px;
                border-radius: 3px;
                line-height: 1.1;
                white-space: nowrap;
            }}
            .tag-stock {{ background: #dcfce7; color: #166534; }}
            .tag-color {{ background: #f1f5f9; color: #475569; }}
            .tag-status-tam {{ background: #e0f2fe; color: #0369a1; }}
            .tag-status-kirik {{ background: #fef3c7; color: #b45309; }}
            .tag-status-tukendi {{ background: #fee2e2; color: #b91c1c; }}
        </style>
    </head>
    <body>
        <div id="productGrid" class="grid-container"></div>
        <script>
            const data = {cards_json};
            const grid = document.getElementById('productGrid');
            
            data.forEach((p) => {{
                const card = document.createElement('div');
                card.className = 'product-card';
                card.dataset.id = p.id;
                
                let statusClass = 'tag-status-tam';
                if(p.status === 'Kırık Beden' || p.status === 'Tek Beden') statusClass = 'tag-status-kirik';
                if(p.status === 'Tükendi') statusClass = 'tag-status-tukendi';
                
                let discountBadge = p.discount > 0 ? `<span class="badge-discount">%${{p.discount}}</span>` : '';
                
                card.innerHTML = `
                    <div class="img-container">
                        <span class="badge-order">#${{p.actual_rank}}</span>
                        ${{discountBadge}}
                        ${{p.image ? `<img src="${{p.image}}" loading="lazy" />` : '<span style="color:#94a3b8;font-size:10px;">Görsel Yok</span>'}}
                    </div>
                    <div class="card-details">
                        <div class="product-title" title="${{p.title}}">${{p.title}}</div>
                        <div class="tags-row">
                            <span class="tag tag-stock">📦 ${{p.stock}}</span>
                            <span class="tag tag-color">🎨 ${{p.color}}</span>
                            <span class="tag ${{statusClass}}">${{p.status}}</span>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            }});
            
            function updateOrderAndSync() {{
                const cards = Array.from(grid.getElementsByClassName('product-card'));
                const orderedIds = [];
                cards.forEach((c, i) => {{
                    const badge = c.querySelector('.badge-order');
                    if (badge) badge.innerText = '#' + (i + 1);
                    orderedIds.push(c.dataset.id);
                }});
                
                // Üstteki Streamlit Textarea kutusunu anında doldur
                try {{
                    const parentTextarea = window.parent.document.querySelector('textarea[aria-label="Sürüklenen Sıra Verisi (Otomatik Kopyalanır):"]');
                    if (parentTextarea) {{
                        parentTextarea.value = JSON.stringify(orderedIds);
                        parentTextarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                }} catch(e) {{}}
            }}

            new Sortable(grid, {{
                multiDrag: true,
                selectedClass: 'sortable-selected',
                multiDragKey: 'Control',
                fallbackTolerance: 3,
                animation: 120,
                ghostClass: 'sortable-ghost',
                onEnd: function() {{
                    updateOrderAndSync();
                }}
            }});
        </script>
    </body>
    </html>
    """
    
    estimated_height = max(500, (len(cards_data) // 4 + 1) * 175)
    components.html(html_code, height=min(estimated_height, 1200), scrolling=True)

else:
    # 📋 Klasik Tablo Modu
    display_cols = [
        "Planlanan Sıra", "image", "Mevcut Sıra", "title", "sku", "color", "season", 
        "total_stock", "active_sizes", "size_status", "discount_pct", "days_old", "price"
    ]
    st.dataframe(
        grid_df[display_cols],
        use_container_width=True,
        height=450,
        column_config={
            "image": st.column_config.ImageColumn("Görsel", width="small"),
            "Planlanan Sıra": st.column_config.NumberColumn("Planlanan", width="small"),
            "Mevcut Sıra": st.column_config.NumberColumn("Mevcut", width="small"),
            "title": st.column_config.TextColumn("Ürün Adı", width="large"),
            "sku": st.column_config.TextColumn("SKU"),
            "color": st.column_config.TextColumn("Renk"),
            "season": st.column_config.TextColumn("Sezon"),
            "total_stock": st.column_config.NumberColumn("Stok"),
            "active_sizes": st.column_config.NumberColumn("Beden"),
            "size_status": st.column_config.TextColumn("Beden Durumu"),
            "discount_pct": st.column_config.NumberColumn("İndirim %"),
            "days_old": st.column_config.NumberColumn("Gün"),
            "price": st.column_config.NumberColumn("Fiyat (TL)", format="%.2f TL")
        }
    )

# ==================== CANLIYA ALMA ====================
st.divider()
st.subheader("🚀 Sıralamayı Vitrinde Canlıya Al")
col_btn, col_info = st.columns([1, 2])

with col_btn:
    if st.button("Shopify'a Gönder ve Vitrini Güncelle", type="primary", use_container_width=True):
        with st.spinner("Shopify koleksiyon sıralaması güncelleniyor..."):
            ordered_ids = df_sorted["product_id"].tolist()
            ok = reorder_shopify_collection(selected_col_id, ordered_ids)
            if ok:
                st.success("🎉 Sıralama Shopify üzerinde başarıyla güncellendi!")
                st.balloons()
            else:
                st.error("Sıralama aktarılırken bir hata oluştu.")

with col_info:
    st.info("💡 Butona bastığında mağazadaki koleksiyon vitrini buradaki sıralamaya göre anında Shopify'da güncellenir.")
