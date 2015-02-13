/****************************************************************************
**
** Copyright (C) 2015 The Qt Company Ltd.
** Contact: http://www.qt.io/licensing
**
** This file is part of Qt Creator.
**
** Commercial License Usage
** Licensees holding valid commercial Qt licenses may use this file in
** accordance with the commercial license agreement provided with the
** Software or, alternatively, in accordance with the terms contained in
** a written agreement between you and The Qt Company.  For licensing terms and
** conditions see http://www.qt.io/terms-conditions.  For further information
** use the contact form at http://www.qt.io/contact-us.
**
** GNU Lesser General Public License Usage
** Alternatively, this file may be used under the terms of the GNU Lesser
** General Public License version 2.1 or version 3 as published by the Free
** Software Foundation and appearing in the file LICENSE.LGPLv21 and
** LICENSE.LGPLv3 included in the packaging of this file.  Please review the
** following information to ensure the GNU Lesser General Public License
** requirements will be met: https://www.gnu.org/licenses/lgpl.html and
** http://www.gnu.org/licenses/old-licenses/lgpl-2.1.html.
**
** In addition, as a special exception, The Qt Company gives you certain additional
** rights.  These rights are described in The Qt Company LGPL Exception
** version 1.1, included in the file LGPL_EXCEPTION.txt in this package.
**
****************************************************************************/

#ifndef MIMETYPEMAGICDIALOG_H
#define MIMETYPEMAGICDIALOG_H

#include "ui_mimetypemagicdialog.h"

namespace Core {
namespace Internal {

struct MagicData
{
    MagicData() {}
    MagicData(const QString &value, const QString &type, int start, int end, int p)
        : m_value(value)
        , m_type(type)
        , m_start(start)
        , m_end(end)
        , m_priority(p) {}

    QString m_value;
    QString m_type;
    int m_start;
    int m_end;
    int m_priority;
};

class MimeTypeMagicDialog : public QDialog
{
    Q_OBJECT

public:
    explicit MimeTypeMagicDialog(QWidget *parent = 0);

    void setMagicData(const MagicData &data);
    MagicData magicData() const;

private slots:
    void applyRecommended(bool checked);
    void validateAccept();

private:
    Ui::MimeTypeMagicDialog ui;
};

} // Internal
} // Core

#endif // MIMETYPEMAGICDIALOG_H