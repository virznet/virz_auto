import os
import random
import time
import requests
import json
import base64
import re
import io
import sys
from bs4 import BeautifulSoup
from requests.auth import HTTPBasicAuth
from PIL import Image

# 콘솔 출력 시 한글 깨짐 방지 설정
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# ==========================================
# 1. 환경 변수 및 설정
# ==========================================
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
WP_USERNAME = os.environ.get('WP_USERNAME', '').strip()
WP_APP_PASSWORD = os.environ.get('WP_APP_PASSWORD', '').replace(' ', '').strip()
WP_BASE_URL = "https://virz.net" 

# 테스트 모드: True일 경우 1개만 즉시 발행하고 종료
IS_TEST = os.environ.get('TEST_MODE', 'false').lower() == 'true'

# ==========================================
# 2. 데이터 로드 및 수집 로직 (지정된 네이버 섹션 대응)
# ==========================================
def load_external_links():
    file_path = "links.json"
    default_links = [{"title": "virz.net", "url": "https://virz.net"}]
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if data else default_links
        except Exception as e:
            print(f"⚠️ links.json 로드 실패: {e}", flush=True)
            return default_links
    return default_links

class TrendScraper:
    """사용자가 지정한 네이버 뉴스 경로에서 데이터를 수집하는 스크래퍼"""
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
        }

    def get_naver_news_custom(self, url):
        """네이버 뉴스 랭킹 또는 섹션/속보 페이지에서 제목 수집"""
        try:
            clean_url = url.strip()
            res = requests.get(clean_url, headers=self.headers, timeout=15)
            res.encoding = res.apparent_encoding if res.apparent_encoding else 'utf-8'
            soup = BeautifulSoup(res.text, 'html.parser')
            
            titles = []
            
            section_items = soup.select(".sa_text_strong")
            if section_items:
                titles.extend([t.text.strip() for t in section_items])
            
            ranking_items = soup.select(".rankingnews_list .list_title")
            if ranking_items:
                titles.extend([t.text.strip() for t in ranking_items])
            
            if not titles:
                alt_items = soup.select(".cluster_text_headline")
                titles.extend([t.text.strip() for t in alt_items])

            unique_titles = list(dict.fromkeys([t for t in titles if t]))
            return unique_titles[:10]
            
        except Exception as e:
            print(f"⚠️ 네이버 뉴스 스크래핑 오류 ({url[:40]}...): {e}", flush=True)
            return []

# ==========================================
# 3. 워드프레스 & 이미지 처리
# ==========================================
def get_recent_posts():
    try:
        res = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts?per_page=10&_fields=title,link", timeout=10)
        if res.status_code == 200:
            return [{"title": p['title']['rendered'], "link": p['link']} for p in res.json()]
    except Exception as e:
        print(f"최근 포스트 로드 오류: {e}", flush=True)
    return []

def generate_image_process(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-4.0-generate-001:predict?key={GEMINI_API_KEY}"
    final_prompt = f"Professional photography for: {prompt}. High resolution, 8k, cinematic lighting. Strictly NO TEXT, NO LETTERS, NO WORDS, NO FONTS."
    payload = {"instances": [{"prompt": final_prompt}], "parameters": {"sampleCount": 1}}
    try:
        response = requests.post(url, json=payload, timeout=150)
        if response.status_code == 200:
            result = response.json()
            b64_data = result['predictions'][0]['bytesBase64Encoded']
            img_data = base64.b64decode(b64_data)
            img = Image.open(io.BytesIO(img_data))
            if img.mode != 'RGB': img = img.convert('RGB')
            out = io.BytesIO()
            img.save(out, format='JPEG', quality=70, optimize=True)
            return out.getvalue()
    except Exception: pass
    return None

def upload_to_wp_media(img_data):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/media"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    headers = {"Content-Disposition": f"attachment; filename=feat_{int(time.time())}.jpg", "Content-Type": "image/jpeg"}
    try:
        res = requests.post(url, auth=auth, headers=headers, data=img_data, timeout=60)
        if res.status_code == 201: return res.json()['id']
    except Exception: pass
    return None

# ==========================================
# 4. 스마트 콘텐츠 생성
# ==========================================
def generate_article(keyword, category, internal_posts, user_links):
    model_id = "gemini-2.5-flash-preview-09-2025"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={GEMINI_API_KEY}"
    
    internal_ref = "내 블로그 추천글:\n" + "\n".join([f"- {p['title']}: {p['link']}" for p in internal_posts]) if internal_posts else ""
    selected_ext = random.sample(user_links, min(len(user_links), 2))
    user_ext_ref = "제공된 외부 링크:\n" + "\n".join([f"- {l['title']}: {l['url']}" for l in selected_ext])

    system_prompt = f"""당신은 {category} 분야의 전문 SEO 블로거입니다. 
키워드 '{keyword}'에 대해 3,000자 이상의 매우 상세하고 가치 있는 블로그 글을 작성하세요.

[필수 사항: JSON 무결성]
- 반드시 유효한 JSON 형식이어야 합니다.
- 'content' 필드 내의 HTML 태그 속성에는 큰따옴표(") 대신 작은따옴표(')를 사용하세요. 
- 모든 본문 내 큰따옴표는 반드시 \\"로 이스케이프하세요.

[휴먼 터치 및 가독성 가이드]
1. 자연스러운 어조: 사람이 직접 쓴 것처럼 친근한 말투를 사용하세요. 전문 블로거의 페르소나를 유지하세요.
2. 모바일 최적화: 한 문단은 3줄 내외로 유지하고, 문단 사이에는 과감하게 줄바꿈을 넣으세요.
3. 태그 생성: 본문 내용과 관련된 키워드 5~8개를 'tags' 리스트에 담아주세요.

JSON 키: 'title', 'content', 'excerpt', 'tags', 'image_prompt'.
"""
    
    user_query = f"{internal_ref}\n\n{user_ext_ref}\n\n키워드: {keyword}\n카테고리: {category}\n위 정보를 바탕으로 완성도 높은 JSON 데이터를 생성하세요."
    payload = {
        "contents": [{"parts": [{"text": user_query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"responseMimeType": "application/json"}
    }
    
    try:
        res = requests.post(url, json=payload, timeout=180)
        if res.status_code == 200:
            raw_response = res.json()['candidates'][0]['content']['parts'][0]['text']
            json_str = raw_response.strip()
            if json_str.startswith("```"):
                json_str = re.sub(r'^`{3}(?:json)?\s*', '', json_str)
                json_str = re.sub(r'\s*`{3}$', '', json_str)
            json_str = "".join(c for c in json_str if ord(c) >= 32 or c in '\n\r\t')
            return json.loads(json_str)
    except Exception as e:
        print(f"⚠️ AI 콘텐츠 생성 실패: {e}", flush=True)
    return None

# ==========================================
# 5. 워드프레스 발행 로직 (태그 처리 보강)
# ==========================================
def post_article(data, mid):
    url = f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/posts"
    auth = HTTPBasicAuth(WP_USERNAME, WP_APP_PASSWORD)
    
    tag_ids = []
    tags_raw = data.get('tags', [])
    
    # 태그 데이터가 리스트인지 문자열인지 확인 후 처리
    if tags_raw:
        if isinstance(tags_raw, str):
            tag_names = [t.strip() for t in tags_raw.split(',') if t.strip()]
        else:
            tag_names = [str(t).strip() for t in tags_raw if str(t).strip()]
            
        for tname in tag_names:
            try:
                # 1. 기존 태그 검색 (정확한 매칭을 위해 리스트 전체 탐색)
                r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                tid = None
                if r.status_code == 200:
                    tags_data = r.json()
                    if isinstance(tags_data, list):
                        for t_obj in tags_data:
                            if t_obj['name'].lower() == tname.lower():
                                tid = t_obj['id']
                                break
                
                # 2. 태그가 없으면 새로 생성
                if not tid:
                    cr = requests.post(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags", auth=auth, json={"name": tname}, timeout=10)
                    if cr.status_code == 201:
                        tid = cr.json()['id']
                    elif cr.status_code == 400: # 이미 존재하는 경우 다시 한 번 검색 시도
                        r = requests.get(f"{WP_BASE_URL.rstrip('/')}/wp-json/wp/v2/tags?search={tname}", auth=auth, timeout=10)
                        if r.status_code == 200:
                            tags_data = r.json()
                            tid = next((t['id'] for t in tags_data if t['name'].lower() == tname.lower()), None)
                
                if tid:
                    tag_ids.append(tid)
            except Exception as e:
                print(f"⚠️ 태그 처리 중 오류 ({tname}): {e}", flush=True)
                continue

    payload = {
        "title": data.get('title', '제목 없음'), 
        "content": data.get('content', ''), 
        "excerpt": data.get('excerpt', ''),
        "tags": tag_ids, 
        "featured_media": mid, 
        "status": "publish"
    }
    
    try:
        res = requests.post(url, auth=auth, json=payload, timeout=40)
        return res.status_code == 201
    except Exception as e:
        print(f"워드프레스 API 발행 오류: {e}", flush=True)
        return False

# ==========================================
# 6. 메인 실행부
# ==========================================
def main():
    if not GEMINI_API_KEY: 
        print("❌ GEMINI_API_KEY 누락", flush=True); return

    user_links = load_external_links()
    recent_posts = get_recent_posts()
    scraper = TrendScraper()
    
    print("🚀 지정된 네이버 뉴스 섹션 분석 및 포스팅 엔진 가동...", flush=True)
    
    jobs = [
        ("https://news.naver.com/section/102", "사회"),
        ("https://news.naver.com/section/105", "IT/과학"),
        ("https://news.naver.com/breakingnews/section/103/241", "건강정보"),
        ("https://news.naver.com/breakingnews/section/103/237", "여행/레저"),
        ("https://news.naver.com/breakingnews/section/103/376", "패션/뷰티"),
        ("https://news.naver.com/breakingnews/section/103/242", "공연/전시")
    ]
    
    pool = []
    for url, cat in jobs:
        print(f"📡 {cat} 뉴스 수집 중...", flush=True)
        items = scraper.get_naver_news_custom(url)
        if not items:
            print(f"⚠️ {cat} 뉴스 수집 실패 (데이터 없음)", flush=True)
        for i in items:
            pool.append({"kw": i, "cat": cat})
        time.sleep(1)
    
    if not pool: 
        print("❌ 수집된 트렌드 키워드가 없습니다.", flush=True); return
    
    num_posts = 1 if IS_TEST else min(len(pool), 5)
    targets = random.sample(pool, num_posts)
    
    for idx, item in enumerate(targets):
        print(f"📝 [{idx+1}/{len(targets)}] '{item['kw']}' ({item['cat']}) 포스팅 시작...", flush=True)
        
        data = generate_article(item['kw'], item['cat'], recent_posts, user_links)
        if not data: continue
        
        mid = None
        if data.get('image_prompt'):
            print("🎨 이미지 생성 및 최적화 중...", flush=True)
            img_data = generate_image_process(data['image_prompt'])
            if img_data: mid = upload_to_wp_media(img_data)
        
        if post_article(data, mid):
            print(f"✅ 발행 성공: {data.get('title')}", flush=True)
        else:
            print("❌ 발행 실패", flush=True)
            
        if not IS_TEST and idx < len(targets) - 1:
            wait = random.randint(900, 1800)
            print(f"⏳ 다음 포스팅까지 {wait//60}분 대기...", flush=True)
            time.sleep(wait)

if __name__ == "__main__":
    main()
