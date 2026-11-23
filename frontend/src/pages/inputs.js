import {feedback, field} from '../components/common/fields.js';
import {empty, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

async function linkSection(dataset, refresh) {
  const message = feedback();
  const [{version, links:records}, {groups}] = await Promise.all([workspace.links(dataset.id), workspace.groups(dataset.id)]);
  const submit = button('登记同票关系', {type:'submit', class:'primary', 'data-testid':'link-submit'});
  const form = session.canWrite && el('form', {class:'fields', onSubmit:handler(submit, message, async event => {
    const data = new FormData(event.target);
    await workspace.addLink(dataset.id, {left_id:data.get('left_id'), right_id:data.get('right_id')});
    await refresh();
  })}, el('div', {class:'form-grid'},
    field({key:'left_id', label:'票据编号甲', type:'string', max_length:300}),
    field({key:'right_id', label:'票据编号乙', type:'string', max_length:300})), submit);
  const recordsTable = table([
    {key:'left_id', label:'票据编号甲'},
    {key:'right_id', label:'票据编号乙'},
    {label:'状态', render:row=>pill(row.active ? '生效中' : '已撤销', row.active ? 'complete' : 'returned')},
    {label:'登记', render:row=>`${row.created_by} · ${date(row.created_at)}`},
    {label:'操作', render:row=>{
      if (!row.active || !session.canWrite) return '—';
      const action = button('撤销关系', {class:'quiet'});
      action.addEventListener('click', handler(action, message, async () => {
        await workspace.revokeLink(dataset.id, row.id);
        await refresh();
      }));
      return action;
    }},
  ], records, {caption:'同票关系记录', empty:'还没有登记同票关系。'});
  const groupsTable = table([
    {key:'key', label:'分组'},
    {key:'members', label:'成员扫描件'},
    {key:'size', label:'件数'},
    {label:'是否计入', render:row=>row.counted ? '计入 1 对' : '待核未计入'},
    {key:'reason', label:'原因'},
  ], groups, {caption:'当前同票分组', empty:'本批次还没有票据。'});
  return panel(`同票关系 · 当前版本 v${version}`,
    p('同一原票反复扫描只应计一次。登记两件扫描件的同票关系后，间接相连的归一组；组内 A、B 判定分别一致才计 1 对，有分歧整组待核。撤销后按剩余关系拆组重算，新运行将固定当前版本。', 'subtle'),
    form, recordsTable, h(3, '当前分组预览'), groupsTable, message);
}

export async function inputs(route, refresh) {
  const {spec,datasets} = workspace;
  const selected = datasets.find(item => item.id === route.id) || datasets[0];
  const error = feedback();
  const sample = button('下载示例 CSV', {class:'quiet',onClick:event=>handler(sample,error,()=>workspace.download('/template',spec.sample_name))(event)});
  const detail = selected && await workspace.getDataset(selected.id,route.offset);
  const columns = spec.fields.map(field => ({key:field.key,label:field.label}));
  const preview = detail ? panel('批次明细', el('div',{class:'actions'},
    el('label',{for:'dataset-id',class:'sr'}, '选择数据批次'),
    el('select',{id:'dataset-id','aria-label':'选择数据批次',onChange:event=>{location.hash=`#inputs/${event.target.value}`;}},
      datasets.map(item=>el('option',{value:item.id,selected:item.id === selected.id}, item.name))),
    link('使用此批次运行',`#run/${detail.id}`,{class:'quiet'})),
    p(`${detail.filename} · ${detail.row_count} 行 · ${date(detail.created_at)}`,'filename'),
    table(columns,detail.rows,{caption:'批次明细',pageSize:16}),
    el('div',{class:'pagination'},
      route.offset > 0 && link('上一批明细',`#inputs/${detail.id}/${Math.max(0,route.offset-16)}`,{class:'quiet'}),
      p(`${detail.rows.length ? route.offset+1 : route.offset}–${route.offset+detail.rows.length} / ${detail.row_count}`),
      route.offset+16 < detail.row_count && link('下一批明细',`#inputs/${detail.id}/${route.offset+16}`,{class:'quiet'})))
    : empty('没有可用的批次。请导入示例或业务 CSV。');
  const submit = button('校验并导入', {type:'submit',class:'primary'});
  const upload = session.canWrite && el('form',{class:'fields',onSubmit:handler(submit,error,async event=>{
    const data = new FormData(event.target);
    const file = data.get('source');
    if (!file?.size) throw new Error('请选择一个 CSV 文件');
    if (file.size > 2_000_000) throw new Error('CSV 最多 2 MB');
    const item = await workspace.upload({name:data.get('batch_name'),filename:file.name,csv_text:await file.text()});
    const target = `#inputs/${item.id}`;
    if (location.hash === target) await refresh();
    else location.hash = target;
  })},field({key:'batch_name',label:'批次名称',type:'string',max_length:120}),
    el('label',{class:'field',for:'source'}, el('span',{},'业务 CSV'),el('input',{id:'source',type:'file',name:'source',accept:'.csv,text/csv',required:true})), submit);
  return el('div',{class:'two-col'},el('div',{class:'wide-panel'},preview,
    selected && await linkSection(selected, refresh)),el('aside',{class:'sidebar-panel'},
    panel('数据导入',p('导入后保留原批次和校验指纹，可用同一份数据复跑。','subtle'),sample,upload,error),
    panel('字段说明',el('dl',{class:'dictionary'},spec.fields.map(item=>el('div',{},el('dt',{},item.label),
      el('dd',{},item.key,item.required === false ? ' · 可空' : ' · 必填',item.options ? ` · ${item.options.join(' / ')}` : '')))))));
}
