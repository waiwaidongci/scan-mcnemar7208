"""同票关系分组：间接相连的扫描件归一组，组内判定一致才计一对。"""


def build_groups(rows, links):
    """按生效同票关系把票据行归组（并查集求连通分量）。

    返回的分组按首成员票据编号排序，每组含 members、size、consistent、
    a_pass/b_pass（仅一致时有值）与中文 reason。快照之外的编号防御性忽略，
    登记时已校验编号属于本批次，且批次内容不可变。
    """
    parent = {}

    def find(item):
        parent.setdefault(item, item)
        root = item
        while parent[root] != root:
            root = parent[root]
        while parent[item] != root:
            parent[item], item = root, parent[item]
        return root

    known = {row['document_id'] for row in rows}
    for left, right in links or []:
        if left not in known or right not in known or left == right:
            continue
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    members = {}
    for row in rows:
        members.setdefault(find(row['document_id']), []).append(row)

    groups = []
    for group_rows in members.values():
        group_rows = sorted(group_rows, key=lambda row: row['document_id'])
        a_votes = {row['a_pass'] for row in group_rows}
        b_votes = {row['b_pass'] for row in group_rows}
        consistent = len(a_votes) == 1 and len(b_votes) == 1
        groups.append({
            'members': [row['document_id'] for row in group_rows],
            'rows': group_rows,
            'size': len(group_rows),
            'consistent': consistent,
            'a_pass': group_rows[0]['a_pass'] if consistent else None,
            'b_pass': group_rows[0]['b_pass'] if consistent else None,
            'reason': _reason(group_rows, a_votes, b_votes, consistent),
        })
    groups.sort(key=lambda group: group['members'][0])
    return groups


def _reason(group_rows, a_votes, b_votes, consistent):
    size = len(group_rows)
    if consistent:
        if size == 1:
            return '无同票关系，单独计 1 对'
        return f'{size} 件同票扫描的 A、B 判定分别一致，合并计 1 对'
    parts = []
    if len(a_votes) > 1:
        passed = sum(1 for row in group_rows if row['a_pass'])
        parts.append(f'现用 A 判定分歧（{passed} 通过 / {size - passed} 未通过）')
    if len(b_votes) > 1:
        passed = sum(1 for row in group_rows if row['b_pass'])
        parts.append(f'候选 B 判定分歧（{passed} 通过 / {size - passed} 未通过）')
    return '；'.join(parts) + '，整组待核未计入'


def display_order(groups):
    """展示顺序：待核组优先，其次多件组，最后单件组；段内按首成员编号排序。"""
    return sorted(groups, key=lambda group: (group['consistent'], -group['size'], group['members'][0]))
