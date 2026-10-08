"""Apply the user-approved FC2 extraction to a new, empty output directory."""
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime
from collections import Counter
from html import unescape
import argparse
import csv
import hashlib
import json
import re
import unicodedata
import yaml

EXCLUDED = {484, 894, 1004, 1784}
APPROVED_RATINGS = {738: 2.0, 1166: 2.9}
DATE_OVERRIDES = {3097: '2008-12-14 05:45:52'}
PREFIX = re.compile(r'^(?:POINT|ＰＯＩＮＴ|POIMT|PONT|POINR|POIONT|POIT)\s*[:：]?\s*', re.I)
MEDIA = {'映画','DVD','BS','試写会','gyao','民放','TV','レンタル','WOWOW','ビデオ','CATV','KML飛行機','ヤフ動','ﾔﾌ動','DVD試写','DVD試写会','DVDコンペ','ヤフ動画','ヤフー動画','公開','民放吹替','英語','映画館','テレ朝','字幕','吹替','VHS','nwa','NW','FC','試写会:自主制作'}
WINDOWS_CHARS = str.maketrans({'\\':'＼','/':'／',':':'：','*':'＊','?':'？','"':'＂','<':'＜','>':'＞','|':'｜'})
EVENT = re.compile(r'上映会|映画祭|フィルムフェスティバル|フィルメックス|シネシティ|ミュージカル|劇団|美術展|DigitalTiff|ホラーフェス|ヴェンダース.*コレクション|[（(]\s*(?:ssff|pff|riff|tiff|ticcf|gtf)(?=[\s)）]|プレ|試写)', re.I)
ARTICLE_CHECKS = {
    116: '評価欄に2.8点と仮定条件の3点：採用する点数を個別確認',
    747: '評価欄に3点と3.05点：採用する点数を個別確認',
    1342: '映画カテゴリだがDSゲームの感想：今回の移行対象か確認',
    2587: 'テレビドラマの第1・2話をまとめた感想：今回の移行対象か確認',
    2814: '映画カテゴリだが書籍の感想：今回の移行対象か確認',
}
TITLE_OVERRIDES = {
    873: 'NARC',  # Remove '5/24スカラ座2他公開(試写会)'.
    1881: 'ヘイジャパ',  # Remove the explicitly marked '(略' suffix; do not infer a full title.
    1876: '犬と私の10の約束',  # Remove the schedule and the repeated viewing annotation only.
    3036: '舟を編む',  # A stray '<' follows the DVD/year annotations in the export.
}

class VisibleText(HTMLParser):
    def __init__(self, paragraphs=False):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.paragraphs=paragraphs
    def handle_data(self,data): self.parts.append(data)
    def handle_starttag(self,tag,attrs):
        if self.paragraphs and tag=='br': self.parts.append('\n')
        elif self.paragraphs and tag in {'div','p','ul','li'}: self.parts.append('\n\n')
    def handle_endtag(self,tag):
        if self.paragraphs and tag in {'div','p','ul','li'}: self.parts.append('\n\n')

def visible(fragment, paragraphs=False):
    parser=VisibleText(paragraphs)
    parser.feed(fragment);parser.close()
    value=''.join(parser.parts)
    return re.sub(r'\n{3,}','\n\n',value).strip() if paragraphs else value.strip()

def signature(text): return text.replace('\r','').replace('\n','').strip()

def clean_title(title, record=None):
    if record in TITLE_OVERRIDES:
        return TITLE_OVERRIDES[record]
    title=unescape(title).strip()
    def parenthetical(m):
        token=unicodedata.normalize('NFKC',m.group(1)).strip()
        if token.lower() in {x.lower() for x in MEDIA} or re.fullmatch(r'[12]\d{3}(?:年度製作版|年)?|[1-9]\d*回目',token):return ''
        return m.group(0)
    title=re.sub(r'[（(]([^()（）]*)[)）]',parenthetical,title)
    title=re.sub(r'[\s　]*[\[［][12]\d{3}年[\]］]','',title)
    title=re.sub(r'[\s　]*(?:[0-9０-９]{1,2}[/／-][0-9０-９]{1,2}日?|[0-9０-９]+年)?[0-9０-９]{1,2}月(?:[0-9０-９]{1,2}日|上旬|中旬|下旬)?公開\s*$','',title)
    title=re.sub(r'[\s　]*(?:[0-9０-９]{1,2}[/／-][0-9０-９]{1,2}日?|正月|初冬|今秋|秋|GW)公開\s*$','',title,flags=re.I)
    title=re.sub(r'[・\s　]+(?:字幕版|吹替版|字幕|吹替)\s*$','',title)
    title=re.sub(r'(?:[\s　]+(?:[12]\d{3}年|DVD|ＤＶＤ|BS|ＢＳ|TV|ＴＶ|吹替|字幕|[1-9１-９]回目))+\s*$','',title,flags=re.I)
    # Removing a viewing parenthesis can leave an adjacent release year without whitespace.
    title=re.sub(r'(?<=\D)[12]\d{3}年\s*$','',title)
    return title.strip()

def parse_headline(headline,record):
    original=headline
    rest=headline
    while True:
        match=PREFIX.match(rest)
        if not match:break
        rest=rest[match.end():]
    prefix_len=len(original)-len(rest)
    if record in APPROVED_RATINGS:
        pattern=r'^強無点[。.]?' if record==738 else r'^2\.9or3\.3'
        m=re.match(pattern,rest)
        if not m: raise ValueError('Approved rating source differs')
        return APPROVED_RATINGS[record],original[:prefix_len+m.end()],rest[m.end():].lstrip() or None,None
    if rest.startswith('強'):return None,None,None,'評価に「強」が付いており意味が未確定'
    m=re.match(r'^([0-9０-９]+(?:[.．][0-9０-９]+)?)点[。.]?',rest)
    if m:
        value=float(unicodedata.normalize('NFKC',m.group(1)))
        return min(5.0,value),original[:prefix_len+m.end()],rest[m.end():].lstrip() or None,None
    m=re.match(r'^無点[。.]?',rest)
    if m:return 3.0,original[:prefix_len+m.end()],rest[m.end():].lstrip() or None,None
    if rest.startswith('-点'):return None,None,None,'旧数値評価期の「-点」は意味を未確認'
    # Matching uses symbols only. Parenthetical notes are recorded verbatim.
    m=re.match(r'^([★☆×△－―ー\-＋+（）()]+)',rest)
    if m:
        symbols=m.group(1)
        end=m.end()
        note=re.match(r'^[（(][^()（）]*[)）]',rest[end:])
        if note:end+=note.end()
        value=3+symbols.count('★')+0.5*symbols.count('☆')-symbols.count('×')-0.5*symbols.count('△')
        return min(5.0,float(value)),original[:prefix_len+end],rest[end:].lstrip() or None,None
    if re.search(r'\d(?:\.\d+)?\s*(?:点|or)',rest):return None,None,None,'冒頭評価が通常形式でない'
    return None,original[:prefix_len] or None,rest.strip() or None,None

def outer_table_end(body,position):
    tokens=list(re.finditer(r'<table\b[^>]*>|</table\s*>',body,re.I))
    stack=[]
    for t in tokens:
        if t.start()>=position:break
        if t.group(0).lower().startswith('</'):
            if stack:stack.pop()
        else:stack.append(t.start())
    if not stack:return None
    level=len(stack)
    for t in tokens:
        if t.start()<position:continue
        level+=-1 if t.group(0).lower().startswith('</') else 1
        if level==0:return t.end()
    raise ValueError('Table is not closed')

def extract_source(body):
    hrs=list(re.finditer(r'<hr\b[^>]*>',body,re.I))
    if len(hrs)==1:
        table=re.search(r'<table\b',body,re.I)
        if not table:raise ValueError('One-HR article lacks an information table boundary')
        lead=body[:table.start()]
        m=re.search(r'<(strong|b)\b[^>]*>(.*?)</\1\s*>',lead,re.S|re.I)
        if not m:raise ValueError('One-HR headline boundary is uncertain')
        headline=visible(m.group(2))
        closes=list(re.finditer(r'</table\s*>',body,re.I))
        if not closes:raise ValueError('One-HR table end is absent')
        begin=max(hrs[0].end(),closes[-1].end())
        return headline,body[begin:],(begin,len(body)), '横線1本・評価見出しとテーブル末尾を使用'
    if len(hrs)==3:
        if visible(body[hrs[-2].end():hrs[-1].start()]):raise ValueError('Extra HR separates nonempty text')
        begin=hrs[-1].end()
        return visible(body[:hrs[0].start()]),body[begin:],(begin,len(body)),'本文前の空の追加横線'
    if len(hrs)!=2:raise ValueError('Unsupported HR count')
    headline=visible(body[:hrs[0].start()])
    begin=hrs[-1].end()
    table_end=outer_table_end(body,hrs[-1].start())
    if table_end is None:return headline,body[begin:],(begin,len(body)),'標準配置'
    td_end=re.search(r'</td\s*>',body[begin:],re.I)
    if not td_end:raise ValueError('Current cell end is absent')
    end=begin+td_end.start()
    cell_fragment=body[begin:end]
    if visible(cell_fragment)=='このアイテムの詳細を見る':
        begin=table_end
        return headline,body[begin:],(begin,len(body)),'横線後の商品リンクを除外・テーブル後の本文'
    if not visible(cell_fragment) and visible(body[table_end:]):
        begin=table_end
        return headline,body[begin:],(begin,len(body)),'横線後の空セルを通過・テーブル後の本人本文'
    if visible(body[table_end:]):raise ValueError('本人本文の左セルとは別にテーブル後にも文字がある：末尾を個別確認')
    if re.search(r'amazon\.co\.jp|rakuten\.co\.jp|<img\b|<iframe\b|<script\b',cell_fragment,re.I):raise ValueError('External image/ad exists in candidate review cell')
    return headline,cell_fragment,(begin,end),'左セルの本人本文・右セルの商品広告を除外'

def make_metadata(title,date,rating,rating_original,short):
    return dict(type='review',title=title,reading=None,reading_status='未調査',release_date=None,release_year=None,genres=[],directors=[],cast=[],filmarks_url=None,filmarks_id=None,review_date=date,rating=rating,rating_display=format(rating,'g')+'点' if rating is not None else None,rating_original=rating_original,short_review=short,source='FC2',source_url=None,image=None)

def migrate(source,output,audit_dir):
    raw=source.read_bytes();text=raw.decode('utf-8-sig')
    if output.exists() and any(output.iterdir()):raise ValueError('Output directory must be empty')
    output.mkdir(parents=True,exist_ok=True);audit_dir.mkdir(parents=True,exist_ok=True)
    items=[];holds=[];excluded=[];verifications=[];stats=Counter()
    for number,block in enumerate(re.split(r'(?m)^--------\r?$',text),1):
        header=block.split('-----',1)[0]
        fields=dict(re.findall(r'^([A-Z][A-Z _]*): ?([^\r\n]*)',header,re.M))
        if fields.get('PRIMARY CATEGORY')!='映画':continue
        if fields.get('STATUS')!='Publish':stats['下書き除外']+=1;continue
        stats['公開映画カテゴリ']+=1
        src_title=fields['TITLE'];src_date=fields['DATE']
        if number in EXCLUDED:
            excluded.append(dict(record=number,title=src_title,date=src_date,reason='ユーザー指定で対象外'));continue
        body=re.search(r'(?ms)^BODY:\r?\n(.*?)(?=^-----\r?$|\Z)',block).group(1)
        if EVENT.search(src_title):
            holds.append(dict(record=number,title=src_title,date=src_date,reason='上映会・映画祭・舞台等：記事ごとに確認',source_body=body));continue
        if number in ARTICLE_CHECKS:
            holds.append(dict(record=number,title=src_title,date=src_date,reason=ARTICLE_CHECKS[number],source_body=body));continue
        try:
            headline,fragment,span,boundary=extract_source(body)
            converted=visible(fragment,True)
            if signature(converted)!=signature(visible(fragment)):raise ValueError('Visible characters changed')
            if not converted:raise ValueError('Empty review body')
            if re.search(r'<img\b|<iframe\b|<script\b|amazon\.co\.jp|rakuten\.co\.jp',fragment,re.I):raise ValueError('External asset/ad remains')
            if number==210:
                m=re.fullmatch(r'(.*?)\n\n『感染』\n(.*?)\n\n『予言』\n(.*)',converted,re.S)
                if not m:raise ValueError('Approved split source headings changed')
                shared,one,two=m.groups()
                data=[('感染',2.5,'予言と同時に見た。',shared+'\n\n『感染』\n'+one),('予言',2.6,'感染と同時に見た。',shared+'\n\n『予言』\n'+two)]
                stats['承認済み分割元記事']+=1
            else:
                rating,rating_original,short,error=parse_headline(headline,number)
                if error:raise ValueError(error)
                data=[(clean_title(src_title,number),rating,short,converted)]
            date=DATE_OVERRIDES.get(number) or datetime.strptime(src_date,'%m/%d/%Y %H:%M:%S').strftime('%Y-%m-%d %H:%M:%S')
            output_names=[]
            for title,rating,short,converted_body in data:
                if not title:raise ValueError('Empty title after qualifier removal')
                meta=make_metadata(title,date,rating,headline if number==210 else rating_original,short)
                name=title.translate(WINDOWS_CHARS).rstrip('. ')+'_'+date[:10]+'.md'
                items.append(dict(record=number,name=name,metadata=meta,body=converted_body,source_title=src_title))
                output_names.append(name)
            verifications.append(dict(record=number,source_title=src_title,source_date=src_date,review_date=date,source_span=span,boundary=boundary,visible_sha256=hashlib.sha256(signature(visible(fragment)).encode()).hexdigest(),split=(number==210),outputs=output_names))
            stats['抽出元記事']+=1;stats['本文文字一致']+=1
        except ValueError as exc:
            holds.append(dict(record=number,title=src_title,date=src_date,reason=str(exc),source_body=body))
    names=Counter(x['name'].casefold() for x in items)
    collisions={k for k,n in names.items() if n>1}
    if collisions:
        records={x['record'] for x in items if x['name'].casefold() in collisions}
        for number in records:
            src=next(x for x in items if x['record']==number)
            holds.append(dict(record=number,title=src['source_title'],date=src['metadata']['review_date'],reason='付記削除後に同日同名ファイルが衝突',source_body=''))
        items=[x for x in items if x['record'] not in records]
        verifications=[x for x in verifications if x['record'] not in records]
        stats['抽出元記事']-=len(records);stats['本文文字一致']-=len(records)
    for item in items:
        md='---\n'+yaml.safe_dump(item['metadata'],allow_unicode=True,sort_keys=False,width=1000).rstrip()+'\n---\n\n'+item['body']+'\n'
        p=output/item['name'];p.write_text(md,encoding='utf-8')
        fm,out_body=p.read_text(encoding='utf-8')[4:].split('\n---\n',1)
        assert yaml.safe_load(fm)==item['metadata']
        assert signature(out_body)==signature(item['body'])
    assert stats['公開映画カテゴリ']==len(excluded)+len(holds)+stats['抽出元記事']
    stats['生成Markdown']=len(items);stats['ユーザー指定除外']=len(excluded);stats['個別確認待ち']=len(holds)
    result=dict(source_sha256=hashlib.sha256(raw).hexdigest(),counts=dict(stats),excluded=excluded,holds=holds,verification=verifications)
    (audit_dir/'fc2-import-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (audit_dir/'approved-decisions.json').write_text(json.dumps(dict(excluded_records=sorted(EXCLUDED),rating_overrides=APPROVED_RATINGS,date_overrides=DATE_OVERRIDES,split_record=210,split_short_reviews=['予言と同時に見た。','感染と同時に見た。'],windows_filename_characters='対応する全角文字'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (audit_dir/'fc2-holds.csv').open('w',encoding='utf-8-sig',newline='') as fh:
        writer=csv.writer(fh);writer.writerow(['レコード番号','旧記事タイトル','元投稿日','確認理由'])
        for item in holds:writer.writerow([item['record'],item['title'],item['date'],item['reason']])
    print(json.dumps(dict(counts=dict(stats),holds=[{k:v for k,v in x.items() if k!='source_body'} for x in holds]),ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path);p.add_argument('audit',type=Path)
    args=p.parse_args();migrate(args.source,args.output,args.audit)
